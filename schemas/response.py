from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class IntentType(str, Enum):
    """用户意图类型"""

    ORDER_QUERY = "order_query"  # 订单查询
    RETURN_REQUEST = "return_request"  # 退换货
    PRODUCT_CONSULT = "product_consult"  # 商品咨询
    COMPLAINT = "complaint"  # 投诉
    AFTER_SALE = "after_sale"  # 售后服务
    PROMOTION = "promotion"  # 优惠活动
    ACCOUNT = "account"  # 账户问题
    GREETING = "greeting"  # 打招呼/闲聊
    OTHER = "other"  # 其他


class CustomerServiceResponse(BaseModel):
    """客服回复的结构化输出"""

    intent: IntentType = Field(description="识别到的用户意图类型")
    confidence: float = Field(
        description="意图识别的置信度，0.0-1.0", ge=0.0, le=1.0
    )
    reply: str = Field(description="给用户的回复内容")
    requires_human: bool = Field(
        description="是否需要转接人工客服", default=False
    )
    follow_up_question: Optional[str] = Field(
        description="需要向用户进一步确认的问题，如果不需要则为 null",
        default=None,
    )
