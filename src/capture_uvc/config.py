"""Capture/UVC 连接配置；相对路径以 vision_learning 根目录为准。"""

from dataclasses import dataclass


@dataclass
class CaptureUvcConfig:
    library_path: str = "../capture/build/bin/capturecore.dll"
    device_id: str = ""
    format_index: int = -1

    def validate(self) -> None:
        if not self.library_path.strip():
            raise ValueError("Capture 内核路径不能为空")
        if type(self.format_index) is not int or self.format_index < -1:
            raise ValueError("Capture 格式编号必须是 -1（自动）或非负整数")
