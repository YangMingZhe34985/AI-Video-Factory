from app.adapters.dashscope_i2v import DashScopeI2VAdapter
from app.adapters.dashscope_image import DashScopeImageAdapter
from app.adapters.dashscope_multimodal_image import DashScopeMultimodalSyncAdapter
from app.adapters.dashscope_r2v import DashScopeR2VFlashAdapter
from app.adapters.dashscope_t2v import DashScopeT2VAdapter
from app.adapters.mock import MockAdapter, MockChatAdapter, MockImageAdapter, MockVideoAdapter
from app.adapters.qwen_chat import QwenChatAdapter


ADAPTERS = {
    "mock": MockAdapter,
    "mock_chat": MockChatAdapter,
    "mock_image": MockImageAdapter,
    "mock_video": MockVideoAdapter,
    "qwen_chat": QwenChatAdapter,
    "dashscope_t2v": DashScopeT2VAdapter,
    "dashscope_image": DashScopeImageAdapter,
    "dashscope_multimodal_sync": DashScopeMultimodalSyncAdapter,
    "dashscope_i2v": DashScopeI2VAdapter,
    "dashscope_r2v_flash": DashScopeR2VFlashAdapter,
}


def get_adapter(adapter_name: str, model=None):
    adapter_class = ADAPTERS.get(adapter_name)
    if adapter_class is None:
        adapter_class = MockAdapter
    return adapter_class(model=model)
