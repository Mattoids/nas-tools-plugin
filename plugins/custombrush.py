import json

import log
from app.plugins import EventHandler
from app.plugins.modules._base import _IPluginModule
from app.utils.types import EventType
from config import Config


class CustomBrush(_IPluginModule):
    # 插件名称
    module_name = "自定义刷流规则"
    # 插件描述
    module_desc = "用于给自定义索引器添加的站点刷流配置免费资源。"
    # 插件图标
    module_icon = "brush.png"
    # 主题色
    module_color = "#02C4E0"
    # 插件版本
    module_version = "1.2"
    # 插件作者
    module_author = "mattoid"
    # 作者主页
    author_url = "https://github.com/Mattoids"
    # 插件配置项ID前缀
    module_config_prefix = "custombrush_"
    # 加载顺序
    module_order = 22
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enable = False
    _site_brush = {}

    @staticmethod
    def get_fields():
        return [
            # 同一板块
            {
                'type': 'div',
                'content': [
                    # 同一行
                    [
                        {
                            'title': '刷流规则',
                            'required': False,
                            'tooltip': '会自动添加到config.yaml文件 laboratory.site_brush 属性中',
                            'type': 'textarea',
                            'content':
                                {
                                    'id': 'site_brush',
                                    'placeholder': ''
                                }
                        }
                    ]
                ]
            }
        ]

    def init_config(self, config=None):
        self._site_brush = self.get_config()
        # 读取配置
        if config:
            self._site_brush = config
            self.update_config(self._site_brush)



    @EventHandler.register(EventType.PluginReload)
    def reload(self, event):
        """
        响应插件重载事件
        """
        plugin_id = event.event_data.get("plugin_id")
        if not plugin_id:
            return
        if plugin_id != self.__class__.__name__:
            return
        return self.init_config(self.get_config())

    def get_state(self):
        return self._enable or self._site_brush

    def stop_service(self):
        """
        退出插件
        """
        pass
