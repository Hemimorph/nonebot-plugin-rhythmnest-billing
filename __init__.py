from nonebot import require

require("nonebot_plugin_alconna")

from .commands import __plugin_meta__

__all__ = ["__plugin_meta__"]
