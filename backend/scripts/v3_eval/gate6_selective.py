"""Gate6 evaluation-only selector: four approved image nodes, all other media local.

Import is side-effect free. capture_originals must happen before meter.install;
install runs only in the isolated evaluation process after a reviewed manifest.
"""
from contextvars import ContextVar
from hashlib import sha256
from pathlib import Path
import re

from gate6_budget import checked_manifest, digest, require
from gate6_transport import ASYNC_URL, SYNC_URL, url_hash

_JOB = ContextVar('gate6_job', default=None)
IMAGE_ADAPTERS = {'dashscope_image', 'dashscope_multimodal_sync', 'dashscope_qwen_image'}


def selected_plan(plan, manifest):
    """Check explicit selection against structure; never infer cast from prompts."""
    manifest = checked_manifest(manifest)
    nodes = {n['id']: n for n in plan['nodes']}
    picks = manifest['nodes']
    require([n['kind'] for n in picks] == ['cast','cast','keyframe','keyframe'], 'Selection order must be two cast then two keyframes')
    characters = []
    for selected in picks:
        node = nodes.get(selected['node_id'])
        require(node is not None and node['tool']=='generate_image' and digest(node)==selected['node_hash'], 'Selected approved node changed')
        require(node.get('model_id')==selected['model'] and node.get('params',{}).get('n')==1, 'Selected model/count is not explicit n=1')
        inputs = node.get('inputs') or {}
        if selected['kind']=='cast':
            require(inputs.get('mode','t2i')=='t2i' and not inputs.get('reference_artifact_ids'), 'Cast sample must have no provider-upload reference')
            role = node.get('characters')
            require(isinstance(role,list) and len(role)==1 and node.get('gate')=='preview', 'Cast must be a single-character preview root')
            require(plan.get('character_references',{}).get(role[0])==[{'ref':node['id']+'.image'}], 'Sample requires one exact generated identity per character')
            characters.append(role[0])
        else:
            require(node.get('model_id') in {'qwen-image-3.0','qwen-image-3.0-pro'}, 'Selected dual-reference model requires reviewed inline-data adapter; no model substitution')
            require(inputs.get('mode')=='i2i' and set(node.get('characters') or [])==set(characters), 'Keyframe must declare both selected characters')
            refs=inputs.get('reference_artifact_ids')
            required=[{'ref':n['node_id']+'.image'} for n in picks[:2]]
            require(isinstance(refs,list) and len(refs)==2 and all(ref in refs for ref in required), 'Keyframe must use exactly both selected identity images')
    require(len(set(characters))==2, 'Two distinct characters required')
    shapes=[digest({k:nodes[item['node_id']].get(k) for k in ('tool','inputs','params','model_id')}) for item in picks]
    require(len(set(shapes))==4, 'Selected nodes would reuse identical execution inputs; choose distinct existing scenes without altering them')
    return characters


def managed_file(value, root, *, must_exist=True):
    """Reject network/drive-relative paths before any resolve can access Windows UNC."""
    value=str(value)
    require(not value.startswith(('\\\\','//')) and not re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:',value)
            or bool(re.match(r'^[A-Za-z]:[\\/]',value)) and not value.startswith(('\\\\','//')), 'Only local managed files are accepted')
    require(not value.startswith(('\\\\?\\','\\\\.\\')), 'Device paths are forbidden')
    path=Path(value)
    if not path.is_absolute(): path=Path(root)/path
    path=path.resolve()
    require(path.is_relative_to(Path(root).resolve()), 'Image escaped managed storage')
    if must_exist: require(path.is_file() and path.stat().st_size>0, 'Selected image file is missing')
    return path


def capture_originals():
    from app import adapters
    return {name:{'class':adapters.ADAPTERS[name], **{method:getattr(adapters.ADAPTERS[name],method)
             for method in ('build_payload','submit','poll','download_outputs')}} for name in IMAGE_ADAPTERS}


class SelectiveMedia:
    def __init__(self, budget, transport, originals, evidence_path):
        self.budget,self.transport,self.originals=budget,transport,originals
        self.path=Path(evidence_path)

    def binding(self, job):
        from app.agent import plan_versions
        from app.plans.policy import validate_job
        run,task,version,node=validate_job(job)
        m=self.budget.manifest
        require(run.run_id==m['run_id'] and version.version==m['plan_version'] and plan_versions.inputs_hash(version.plan)==m['plan_hash'], 'Dispatch not bound to selected approved Plan')
        selected_plan(version.plan,m)
        require(node['id'] in self.budget.nodes and digest(node)==self.budget.nodes[node['id']]['node_hash'], 'Not a selected image node')
        require(task.attempt==1, 'Sample does not authorize automatic generation retries')
        require(task.inputs.get('model_id')==node['model_id'] and task.inputs.get('params',{}).get('n')==1, 'Resolved model/count changed')
        invocation=(job.config or {}).get('skill',{}).get('invocation_id')
        return run,task,node,{'node_id':node['id'],'node_hash':digest(node),'model':node['model_id'],
            'inputs_hash':task.inputs_hash,'job_id':job.job_id,'invocation_id':invocation,
            'attempt_key':f"{run.run_id}:{version.version}:{task.node_id}:1"}

    def references(self, run, task, node):
        from app.models import PlanNodeTask
        from app.plans.execution import artifact_for_run
        from app.services.storage_service import StorageService
        ids=task.inputs.get('reference_artifact_ids') or []
        if self.budget.nodes[node['id']]['kind']=='cast':
            require(not ids, 'Cast dispatch acquired an undeclared reference')
            return []
        casts={n['node_id'] for n in self.budget.manifest['nodes'] if n['kind']=='cast'}
        expected=[]
        for ref in node['inputs']['reference_artifact_ids']:
            source=ref['ref'].split('.')[0]
            require(source in casts, 'Unselected keyframe reference')
            cast=PlanNodeTask.query.filter_by(run_id=run.run_id,plan_version=task.plan_version,node_id=source).one()
            require(cast.status=='success', 'Real identity reference is not complete')
            aid=(cast.output or {}).get('image')
            artifact=artifact_for_run(run,aid,'image')
            path=managed_file(artifact.file_path,StorageService.root())
            sha=sha256(path.read_bytes()).hexdigest()
            with self.budget.connect() as db:
                receipt=db.execute('''SELECT d.sha256 FROM gate6_images i JOIN gate6_image_downloads d ON d.reservation_id=i.id
                    WHERE i.node_id=? AND i.status='success' AND i.actual_images=1''',(source,)).fetchall()
            require(len(receipt)==1 and receipt[0]['sha256']==sha, 'Reference bytes lack the exact real-generation receipt')
            expected.append((aid,sha))
        require(ids==[item[0] for item in expected], 'Resolved reference IDs/order changed')
        return [item[1] for item in expected]

    def adapter(self, name, model):
        job=_JOB.get()
        require(job is not None, 'Selected adapter requires server NodeRunner dispatch')
        controller=self
        original=self.originals[name]
        base=original['class']
        class SelectedAdapter(base):
            def build_payload(self,inputs,params):
                from app.services.storage_service import StorageService
                run,task,node,proof=controller.binding(job)
                refs=controller.references(run,task,node)
                paths=inputs.get('source_images') or ([inputs['source_image']] if inputs.get('source_image') else [])
                require(isinstance(paths,list) and all(isinstance(p,str) for p in paths), 'Unexpected image references')
                hashes=[sha256(managed_file(p,StorageService.root()).read_bytes()).hexdigest() for p in paths]
                require(hashes==refs, 'Payload input files do not match frozen cast references')
                require(not refs or name=='dashscope_qwen_image', 'This sample permits inline local references only; uploads remain disabled')
                payload=original['build_payload'](self,inputs,params)
                proof.update(reference_hashes=refs,payload_hash=digest(payload),endpoint=self.create_url())
                require(proof['endpoint'] in {ASYNC_URL,SYNC_URL}, 'Workspace endpoint is not authorized')
                self._gate6_proof=proof
                return payload
            def submit(self,payload):
                require(hasattr(self,'_gate6_proof') and digest(payload)==self._gate6_proof['payload_hash'], 'Unbound selected payload')
                controller.binding(job)
                with controller.transport.permit(self._gate6_proof):
                    return original['submit'](self,payload)
            def poll(self,task_id):
                _r,_t,_n,proof=controller.binding(job)
                with controller.transport.permit(proof):
                    return original['poll'](self,task_id)
            def download_outputs(self,response,output_dir):
                from PIL import Image
                from app.services.storage_service import StorageService
                _r,_t,node,proof=controller.binding(job)
                root=StorageService.root()
                managed_file(output_dir,root,must_exist=False)
                if response.get('expected_output_path'): managed_file(response['expected_output_path'],root,must_exist=False)
                with controller.transport.permit(proof):
                    values=original['download_outputs'](self,response,output_dir)
                require(len(values)==1, 'Selected download must contain one image')
                path=managed_file(values[0],root)
                with Image.open(path) as image: image.verify()
                with controller.budget.connect() as db:
                    rows=db.execute("SELECT id FROM gate6_images WHERE node_id=? AND status='success' AND actual_images=1",(node['id'],)).fetchall()
                require(len(rows)==1, 'Ambiguous selected output receipt')
                controller.budget.record_download(rows[0]['id'],url_hash=url_hash(response['result_url']),
                    sha256_value=sha256(path.read_bytes()).hexdigest(),byte_count=path.stat().st_size)
                return values
        return SelectedAdapter(model=model)

    def install(self):
        from app import adapters
        from app.services.node_runner import NodeRunner
        import mock_media
        require(mock_media.CONTROLLER is None, 'Do not install legacy mock_media before the selective controller')
        mock_media.CONTROLLER=mock_media.MediaController(self.path)
        original_run=NodeRunner.run
        def run(runner,job,node,node_run):
            token=_JOB.set(job)
            try: return original_run(runner,job,node,node_run)
            finally: _JOB.reset(token)
        self.transport.meter._patch(NodeRunner,'run',run)
        for name,kind in mock_media.MEDIA_NAMES.items():
            def factory(model=None,_name=name,_kind=kind):
                job=_JOB.get()
                marker=(job.config or {}).get('agent_plan',{}) if job is not None else {}
                selected=(marker.get('run_id')==self.budget.manifest['run_id'] and marker.get('node_id') in self.budget.nodes)
                if selected:
                    require(_kind=='image' and _name in IMAGE_ADAPTERS, 'Selected node routed to a nonimage adapter')
                    return self.adapter(_name,model)
                return (mock_media.LocalImageAdapter if _kind=='image' else mock_media.LocalVideoAdapter)(model=model)
            adapters.ADAPTERS[name]=factory
        previous_summary=mock_media.CONTROLLER.summary
        def summary():
            value=previous_summary()
            value['actual_real_media_http_calls']=self.budget.snapshot()['image_post_attempts']
            value['evidence']='Exactly the manifest-selected images use guarded real adapters; every other generation adapter is local Mock.'
            return value
        mock_media.CONTROLLER.summary=summary
        mock_media.CONTROLLER.event('gate6_selective_installed',selected_nodes=list(self.budget.nodes),real_video_limit=0)
        return mock_media.CONTROLLER
