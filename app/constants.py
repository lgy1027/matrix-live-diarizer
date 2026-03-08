"""常量定义"""

# ASR 幻觉词
ASR_HALLUCINATIONS = ["谢谢。", "大家再见。", "字幕由", "感谢收看"]

# 标点符号
PUNCTUATION_CHARS = " 。，？！.,?!"

# WebSocket
WS_MSG_TYPE_TEXT = "text"
WS_MSG_TYPE_SYSTEM = "system"
WS_CLOSE_NORMAL = 1000
WS_CLOSE_ERROR = 1011

# 说话人
SPEAKER_ID_PREFIX = "Spk_"
SYSTEM_SPEAKER = "SYSTEM"
UNKNOWN_SPEAKER = "Unknown"
FILE_UPLOAD_SESSION = "file_upload_service"

# 应用信息
APP_TITLE = "Matrix Live Diarizer Pro"
APP_DESCRIPTION = "实时音频转写与说话人识别系统"