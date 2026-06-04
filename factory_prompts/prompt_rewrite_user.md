# Task

请将输入提示词改写为两个分支专用提示词：

- `r2v_flash`
- `i2v`

# Inputs

T2V Prompt:
{{t2v_prompt}}

First Frame Prompt:
{{first_frame_prompt}}

# Requirements

## r2v_flash

基于 `T2V Prompt` 改写为参考图生视频版本，保持场景、镜头、动作、氛围一致，强化人物身份锁定与参考图一致性。

## i2v

基于 `First Frame Prompt` 改写为图生视频版本，保持首帧连续性，重点描述自然动作、镜头运动与动态细节，内容简洁可控。

# Output

{
  "r2v_flash": "...",
  "i2v": "..."
}