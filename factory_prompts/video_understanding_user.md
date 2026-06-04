# Task

分析输入视频，并按既定规则生成两个字段：

- `t2v`
- `first_frame_image`

# Requirements

- `t2v`：用于视频生成，突出主体、场景、镜头、动作、氛围，要求markdown格式
- `first_frame_image`：用于首帧图生成，突出静态构图、主体姿态、光影、细节质感，要求markdown格式
- 内容具体、可执行、可复用
- 仅输出 JSON object

# Output

{
  "t2v": "...",
  "first_frame_image": "..."
}