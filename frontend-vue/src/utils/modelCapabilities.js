// Provider capability metadata alone never grants executable task permissions.
const generationModes = {
  text_to_image: ['t2i', 'i2i'], text_to_video: ['t2v'],
  image_to_video: ['i2v'], reference_to_video: ['r2v'],
}

export function supportsTaskType(model, taskType) {
  return model?.task_type === taskType
    || (generationModes[taskType] || []).some((mode) => model?.capabilities?.modes?.includes(mode))
}
