import random
import json
import re
from datetime import datetime, timedelta
from threading import Event, Lock
from time import sleep

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from jinja2 import Template

from app.downloader import Downloader
from app.media import DouBan
from app.media.meta import MetaInfo
from app.plugins import EventHandler
from app.plugins.modules._base import _IPluginModule
from app.searcher import Searcher
from app.subscribe import Subscribe
from app.utils import ExceptionUtils, RequestUtils
from app.utils.types import SearchType, RssType, EventType, MediaType
from config import Config
from web.backend.web_utils import WebUtils

lock = Lock()

class InvitesSignin(_IPluginModule):
    # 插件名称
    module_name = "药丸签到"
    # 插件描述
    module_desc = "药丸论坛签到。"
    # 插件图标
    module_icon = "invites.png"
    # 主题色
    module_color = "#FFFFFF"
    # 插件版本
    module_version = "1.1"
    # 插件作者
    module_author = "thsrite"
    # 作者主页
    author_url = "https://github.com/thsrite"
    # 插件配置项ID前缀
    module_config_prefix = "invitessignin_"
    # 加载顺序
    module_order = 24
    # 可使用的用户级别
    auth_level = 2

    # 私有属性
    _scheduler = None
    # 开关属性
    _enabled = False
    # 任务执行间隔
    _cron = None
    _cookie = None
    _onlyonce = False
    _notify = False


    @staticmethod
    def get_fields():
        return [
            # 同一板块
            {
                'type': 'div',
                'content': [
                    [
                        {
                            'title': '开启插件',
                            'required': "",
                            'tooltip': '开启后，将定时对药丸论坛进行签到。',
                            'type': 'switch',
                            'id': 'enabled',
                        },
                        {
                            'title': '运行时通知',
                            'required': "",
                            'tooltip': '开启后，将通知签到结果。',
                            'type': 'switch',
                            'id': 'notify',
                        },
                        {
                            'title': '立即运行一次',
                            'required': "",
                            'tooltip': '开启后，将立即运行一次',
                            'type': 'switch',
                            'id': 'onlyonce',
                        }
                    ],
                    [
                        {
                            'title': '签到周期',
                            'required': "required",
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'cron',
                                    'placeholder': '0 0 0 ? *',
                                }
                            ]
                        },
                        {
                            'title': '药丸cookie',
                            'required': "required",
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'cookie',
                                    'placeholder': '药丸cookie',
                                }
                            ]
                        }
                    ],
                ]
            }
        ]

    def init_config(self, config=None):
        # 停止运行
        self.stop_service()

        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._cookie = config.get("cookie")
            self._notify = config.get("notify")
            self._onlyonce = config.get("onlyonce")

            # 加载模块
        if self._enabled:
            # 定时服务
            self._scheduler = BackgroundScheduler(timezone=Config().get_timezone())

            if self._cron:
                try:
                    self._scheduler.add_job(func=self.__signin,
                                            trigger=CronTrigger.from_crontab(self._cron),
                                            name="药丸签到")
                except Exception as err:
                    self.error(f"定时任务配置错误：{str(err)}")

            if self._onlyonce:
                self.info(f"药丸签到服务启动，立即运行一次")
                self._scheduler.add_job(func=self.__signin, trigger='date',
                                        run_date=datetime.now(tz=pytz.timezone(Config().get_timezone())) + timedelta(seconds=3),
                                        name="药丸签到")
                # 关闭一次性开关
                self._onlyonce = False
                self.update_config({
                    "onlyonce": False,
                    "cron": self._cron,
                    "enabled": self._enabled,
                    "cookie": self._cookie,
                    "notify": self._notify,
                })

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def get_state(self):
        return self._enabled

    def stop_service(self):
        """
        停止插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            self.error("退出插件失败：%s" % str(e))

    def __signin(self):
        """
        药丸签到
        """
        res = RequestUtils(cookies=self._cookie).get_res(url="https://invites.fun")
        if not res or res.status_code != 200:
            self.error("请求药丸错误")
            return

        # 获取csrfToken
        pattern = r'"csrfToken":"(.*?)"'
        csrfToken = re.findall(pattern, res.text)
        if not csrfToken:
            self.error("请求csrfToken失败")
            return

        csrfToken = csrfToken[0]
        self.info(f"获取csrfToken成功 {csrfToken}")

        # 获取userid
        pattern = r'"userId":(\d+)'
        match = re.search(pattern, res.text)

        if match:
            userId = match.group(1)
            self.info(f"获取userid成功 {userId}")
        else:
            self.error("未找到userId")
            return

        headers = {
            "X-Csrf-Token": csrfToken,
            "X-Http-Method-Override": "PATCH",
            "Cookie": self._cookie
        }

        data = {
            "data": {
                "type": "users",
                "attributes": {
                    "canCheckin": False,
                    "totalContinuousCheckIn": 2
                },
                "id": userId
            }
        }

        # 开始签到
        res = RequestUtils(headers=headers).post_res(url=f"https://invites.fun/api/users/{userId}", json=data)

        if not res or res.status_code != 200:
            self.error("药丸签到失败")
            return

        sign_dict = json.loads(res.text)
        money = sign_dict['data']['attributes']['money']
        totalContinuousCheckIn = sign_dict['data']['attributes']['totalContinuousCheckIn']

        # 发送通知
        if self._notify:
            self.send_message(
                title="【药丸签到任务完成】",
                text=f"累计签到 {totalContinuousCheckIn} \n"
                     f"剩余药丸 {money}")