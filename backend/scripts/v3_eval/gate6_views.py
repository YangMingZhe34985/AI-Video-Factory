"""Deterministic evaluation-only display inputs; original artifacts never change."""
from hashlib import sha256
import io
from pathlib import Path

from gate6_budget import require

MAX_EDGE=1024
MAX_IMAGE_BYTES=512*1024
MAX_TOTAL_BYTES=4*MAX_IMAGE_BYTES
TRANSFORM={'format':'JPEG','max_edge':MAX_EDGE,'quality':85,'subsampling':2,'optimize':False,
           'resample':'LANCZOS','alpha_background':'#FFFFFF','crop':False,'enhance':False}


def make_view(source,destination):
    from PIL import Image,ImageOps,__version__
    source,destination=Path(source),Path(destination)
    raw=source.read_bytes(); original_hash=sha256(raw).hexdigest()
    with Image.open(io.BytesIO(raw)) as image:
        require(getattr(image,'n_frames',1)==1,'Identity display input requires a still image')
        source_size=list(image.size)
        # The visible source orientation is respected; no crop or enhancement.
        transposed=ImageOps.exif_transpose(image)
        orientation_applied=transposed.size!=image.size or image.getexif().get(274,1)!=1
        rgba=transposed.convert('RGBA')
        rgb=Image.new('RGB',rgba.size,'white'); rgb.paste(rgba,mask=rgba.getchannel('A'))
        rgb.thumbnail((MAX_EDGE,MAX_EDGE),Image.Resampling.LANCZOS)
        buffer=io.BytesIO(); rgb.save(buffer,format='JPEG',quality=85,subsampling=2,optimize=False)
        data=buffer.getvalue(); size=list(rgb.size)
    require(len(data)<=MAX_IMAGE_BYTES,'Fixed identity JPEG exceeds 512 KiB; do not change transform or call vision')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open('xb') as stream: stream.write(data)
    require(sha256(source.read_bytes()).hexdigest()==original_hash,'Original source changed during display conversion')
    return {'source_path':str(source.resolve()),'source_sha256':original_hash,'source_bytes':len(raw),'source_size':source_size,
            'path':str(destination.resolve()),'sha256':sha256(data).hexdigest(),'bytes':len(data),'size':size,
            'transform':{**TRANSFORM,'exif_orientation_applied':orientation_applied,'pillow_version':__version__}}


def maximum_credit_reserve(rate):
    # 4 fixed maximum image data URLs plus 64 KiB textual/schema framing and
    # output-token reserve. The exact messages are still priced by Registry.
    from decimal import Decimal
    maximum_prompt_bytes=4*(4*((MAX_IMAGE_BYTES+2)//3)+64)+65536
    return float(Decimal(str(rate))*Decimal(maximum_prompt_bytes+4000)/Decimal(1000))


def preflight_budget(run,plan,manifest):
    from app.models import ModelRegistry
    from app.tools.agent_chat import resolve_agent_model
    from app.tools.budget import BudgetGuard,estimate_model_cost
    from app.tools.chat_cost import token_rate
    vision=resolve_agent_model('vision',mode='image_understanding')
    require(vision.model_id=='qwen3.7-plus','Unexpected vision model')
    rate=token_rate(vision); require(rate is not None,'Identity input reserve requires token pricing')
    maximum=maximum_credit_reserve(rate)
    selected={n['node_id'] for n in manifest['nodes']}
    node_costs={n['id']:estimate_model_cost(ModelRegistry.query.filter_by(model_id=n['model_id']).one(),n['params'])
                for n in plan['nodes'] if n['id'] in selected}
    spent=BudgetGuard.spent(run.run_id); limit=run.request['budget_limit']
    report={'run_limit':limit,'spent_before':spent,'selected_image_credits':node_costs,
       'maximum_identity_reservation':maximum,'max_input_bytes':MAX_TOTAL_BYTES,'transform':TRANSFORM,
       'required_before_remaining_mock':spent+sum(node_costs.values())+maximum,
       'assumption':'Fixed derivative cap; original artifacts remain intact. Later Mock nodes retain normal product charges.'}
    total=plan.get('estimates',{}).get('total_credits')
    report['approved_plan_estimate']=total
    report['required_including_remaining_mock']=(spent+float(total)+maximum) if isinstance(total,(int,float)) and not isinstance(total,bool) else None
    report['can_cover_selected_and_vision']=report['required_before_remaining_mock']<=limit
    report['can_cover_full_plan_and_vision']=(report['required_including_remaining_mock']<=limit) if report['required_including_remaining_mock'] is not None else None
    return report
