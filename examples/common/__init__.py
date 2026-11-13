"""教材共用的合成业务环境；不接入真实订单或支付系统。"""

from .sandbox import Sandbox, seed_state

__all__ = ["Sandbox", "seed_state"]
