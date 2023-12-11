import re
import os
import copy
import json
import time
import base64
import zhconv
import requests
from random import choice
from datetime import datetime, timedelta
from threading import Event, Lock
from functools import lru_cache
from time import sleep

import pytz
from requests.exceptions import RequestException
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from jinja2 import Template

from app.media.tmdbv3api import TMDbException
from app.media.tmdbv3api.as_obj import AsObj
from app.media.tmdbv3api.tmdb import TMDb
from app.media.doubanapi import DoubanApi
from app.mediaserver import MediaServer
from app.downloader import Downloader
from app.media import DouBan
from app.media.meta import MetaInfo
from app.plugins import EventHandler
from app.plugins.modules._base import _IPluginModule
from app.searcher import Searcher
from app.subscribe import Subscribe
from app.utils import ExceptionUtils, RequestUtils, StringUtils
from app.utils.types import SearchType, RssType, EventType, MediaType
from app.utils.commons import retry
from config import Config
from web.backend.web_utils import WebUtils

lock = Lock()

class PersonMeta(_IPluginModule):
    # 插件名称
    module_name = "演职人员刮削"
    # 插件描述
    module_desc = "刮削演职人员图片以及中文名称。"
    # 插件图标
    module_icon = "actor.png"
    # 主题色
    module_color = "#E66E72"
    # 插件版本
    module_version = "1.0"
    # 插件作者
    module_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    module_config_prefix = "personmeta_"
    # 加载顺序
    module_order = 25
    # 可使用的用户级别
    auth_level = 2

    # 退出事件
    _event = Event()

    # 私有属性
    _scheduler = None
    tmdb = None
    douban = None
    mschain = None
    doubanapi = None
    _remaining = 40
    _session = None
    _enabled = False
    _onlyonce = False
    _reset = None
    _cron = None
    _delay = 0
    _type = "all"
    _remove_nozh = False
    _apikey = None
    _host = None
    _user = None

    _user_agents = [
        "api-client/1 com.douban.frodo/7.22.0.beta9(231) Android/23 product/Mate 40 vendor/HUAWEI model/Mate 40 brand/HUAWEI  rom/android  network/wifi  platform/AndroidPad"
        "api-client/1 com.douban.frodo/7.18.0(230) Android/22 product/MI 9 vendor/Xiaomi model/MI 9 brand/Android  rom/miui6  network/wifi  platform/mobile nd/1",
        "api-client/1 com.douban.frodo/7.1.0(205) Android/29 product/perseus vendor/Xiaomi model/Mi MIX 3  rom/miui6  network/wifi  platform/mobile nd/1",
        "api-client/1 com.douban.frodo/7.3.0(207) Android/22 product/MI 9 vendor/Xiaomi model/MI 9 brand/Android  rom/miui6  network/wifi platform/mobile nd/1"]


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
                            'tooltip': '开启后，将定时对库存演职人员数据进行更新。',
                            'type': 'switch',
                            'id': 'enabled',
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
                            'title': '入库延迟时间（秒）',
                            'required': "required",
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'delay',
                                    'placeholder': '入库延迟时间（秒）',
                                }
                            ]
                        },
                        {
                            'title': '刮削条件',
                            'required': "required",
                            'type': 'select',
                            'content': [
                                {
                                    'id': 'type',
                                    'options': {
                                        'all': '全部',
                                        'name': '演员非中文',
                                        'role': '角色非中文'
                                    },
                                    'default': 'all',
                                }
                            ]
                        }
                    ],
                    [
                        {
                            'title': '删除非中文演员',
                            'required': "",
                            'type': 'switch',
                            'id': 'remove_nozh',
                        }
                    ],
                ]
            }
        ]

    def init_config(self, config=None):
        self.tmdb = TMDb()
        self.douban = DouBan()
        self.mschain = MediaServer()
        self.doubanapi = DoubanApi()
        self._session = requests.Session()

        # 停止运行
        self.stop_service()

        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._cron = config.get("cron")
            self._type = config.get("type") or "all"
            self._delay = config.get("delay") or 0
            self._remove_nozh = config.get("remove_nozh") or False

        # 停止现有任务
        self.stop_service()

        # 启动服务
        if self._enabled or self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=Config().get_timezone())
            if self._cron or self._onlyonce:
                if self._cron:
                    try:
                        self._scheduler.add_job(func=self.scrap_library,
                                                trigger=CronTrigger.from_crontab(self._cron),
                                                name="演职人员刮削")
                        self.info(f"演职人员刮削服务启动，周期：{self._cron}")
                    except Exception as e:
                        self.error(f"演职人员刮削服务启动失败，错误信息：{str(e)}")
                        self.systemmessage.put(f"演职人员刮削服务启动失败，错误信息：{str(e)}")
                if self._onlyonce:
                    self._scheduler.add_job(func=self.scrap_library, trigger='date',
                                            run_date=datetime.now(
                                                tz=pytz.timezone(Config().get_timezone())) + timedelta(seconds=3)
                                            )
                    self.info(f"演职人员刮削服务启动，立即运行一次")
                    # 关闭一次性开关
                    self._onlyonce = False
                    # 保存配置
                    self.update_config({
                        "enabled": self._enabled,
                        "onlyonce": self._onlyonce,
                        "cron": self._cron,
                        "type": self._type,
                        "delay": self._delay,
                        "remove_nozh": self._remove_nozh
                    })

            if self._scheduler.get_jobs():
                # 启动服务
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
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            self.error("退出插件失败：%s" % str(e))

    @EventHandler.register(EventType.TransferFinished)
    def scrap_rt(self, event: Event):
        """
        根据事件实时刮削演员信息
        """
        if not self._enabled:
            return
        # 事件数据
        mediainfo: MediaInfo = event.event_data.get("mediainfo")
        meta: MetaBase = event.event_data.get("meta")
        if not mediainfo or not meta:
            return
        # 延迟
        if self._delay:
            time.sleep(int(self._delay))
        # 查询媒体服务器中的条目
        existsinfo = self.chain.media_exists(mediainfo=mediainfo)
        if not existsinfo or not existsinfo.itemid:
            self.warn(f"演职人员刮削 {mediainfo.title_year} 在媒体库中不存在")
            return
        # 查询条目详情
        iteminfo = self.mschain.iteminfo(server=existsinfo.server, item_id=existsinfo.itemid)
        if not iteminfo:
            self.warn(f"演职人员刮削 {mediainfo.title_year} 条目详情获取失败")
            return
        # 刮削演职人员信息
        self.__update_item(server=existsinfo.server, item=iteminfo,
                           mediainfo=mediainfo, season=meta.begin_season)

    def scrap_library(self):
        """
        扫描整个媒体库，刮削演员信息
        """
        # 所有媒体服务器
        mschain_type = self.mschain.get_type()
        if not mschain_type:
            return
        # 扫描所有媒体库
        server = mschain_type.value.lower()
        if server not in ["plex"]:
            self._host = Config().get_config(server).get("host")
            self._apikey = Config().get_config(server).get("api_key")
            self._user = self.get_user(Config().current_user)

        self.info(f"开始刮削服务器 {server} 的演员信息 ...")
        for library in self.mschain.get_libraries():
            self.info(f"开始刮削媒体库 {library.get('name')} 的演员信息 ...")
            for item in self.mschain.get_items(library.get('id')):
                self.info(f"{item}")
                if not item:
                    continue
                if not item.get('id'):
                    continue
                if "Series" not in item.get('type') and "Movie" not in item.get('type'):
                    continue
                if self._event.is_set():
                    self.info(f"演职人员刮削服务停止")
                    return
                # 处理条目
                self.info(f"开始刮削 {item.get('title')} 的演员信息 ...")
                self.__update_item(server=server, item=item)
                self.info(f"{item.get('title')} 的演员信息刮削完成")
            self.info(f"媒体库 {library.get('name')} 的演员信息刮削完成")
        self.info(f"服务器 {server} 的演员信息刮削完成")

    def __update_peoples(self, server: str, itemid: str, iteminfo: dict, douban_actors):
        # 处理媒体项中的人物信息
        """
        "People": [
            {
              "Name": "丹尼尔·克雷格",
              "Id": "33625",
              "Role": "James Bond",
              "Type": "Actor",
              "PrimaryImageTag": "bef4f764540f10577f804201d8d27918"
            }
        ]
        """
        peoples = []
        # 更新当前媒体项人物
        for people in iteminfo["People"] or []:
            if self._event.is_set():
                self.info(f"演职人员刮削服务停止")
                return
            if not people.get("Name"):
                continue
            if StringUtils.is_chinese(people.get("Name")) \
                    and StringUtils.is_chinese(people.get("Role")):
                peoples.append(people)
                continue
            info = self.__update_people(server=server, people=people,
                                        douban_actors=douban_actors)
            if info:
                peoples.append(info)
            elif not self._remove_nozh:
                peoples.append(people)
        # 保存媒体项信息
        if peoples:
            iteminfo["People"] = peoples
            self.set_iteminfo(server=server, itemid=itemid, iteminfo=iteminfo, service=self)

    def __update_item(self, server, item, mediainfo=None, season=None):
        """
        更新媒体服务器中的条目
        """
        def __need_trans_actor(_item):
            """
            是否需要处理人物信息
            """
            if self._type == "name":
                # 是否需要处理人物名称
                _peoples = [x for x in _item.get("People", []) if
                            (x.get("Name") and not StringUtils.is_chinese(x.get("Name")))]
            elif self._type == "role":
                # 是否需要处理人物角色
                _peoples = [x for x in _item.get("People", []) if
                            (x.get("Role") and not StringUtils.is_chinese(x.get("Role")))]
            else:
                _peoples = [x for x in _item.get("People", []) if
                            (x.get("Name") and not StringUtils.is_chinese(x.get("Name")))
                            or (x.get("Role") and not StringUtils.is_chinese(x.get("Role")))]
            if _peoples:
                return True
            return False

        # 识别媒体信息
        if not mediainfo:
            if not item.get('tmdbid'):
                self.warn(f"{item.get('title')} 未找到tmdbid，无法识别媒体信息")
                return
            mtype = MediaType.TV if item.get('type') in ['Series', 'show'] else MediaType.MOVIE
            mediainfo = WebUtils.get_mediainfo_from_id(mtype=mtype, mediaid=item.get('tmdbid'))
            if not mediainfo:
                self.warn(f"{item.get('title')} 未识别到媒体信息")
                return

        # 获取媒体项
        iteminfo = self.get_iteminfo(server=server, itemid=item.get('id'), service=self)
        if not iteminfo:
            self.warn(f"{item.get('title')} 未找到媒体项")
            return

        if __need_trans_actor(iteminfo):
            # 获取豆瓣演员信息
            self.info(f"开始获取 {item.get('title')} 的豆瓣演员信息 ...")
            douban_actors = self.__get_douban_actors(mediainfo=mediainfo, season=season)
            self.__update_peoples(server=server, itemid=item.get('id'), iteminfo=iteminfo, douban_actors=douban_actors)
        else:
            self.info(f"{item.get('title')} 的人物信息已是中文，无需更新")

        # 处理季和集人物
        if iteminfo.get("Type") and "Series" in iteminfo["Type"]:
            # 获取季媒体项
            seasons = self.get_items(server=server, parentid=item.get('id'), mtype="Season", service=self)
            if not seasons:
                self.warn(f"{item.get('title')} 未找到季媒体项")
                return
            for season in seasons["Items"]:
                # 获取豆瓣演员信息
                season_actors = self.__get_douban_actors(mediainfo=mediainfo, season=season.get("IndexNumber"))
                # 如果是Jellyfin，更新季的人物，Emby/Plex季没有人物
                if server == "jellyfin":
                    seasoninfo = self.get_iteminfo(server=server, itemid=season.get("Id"), service=self)
                    if not seasoninfo:
                        self.warn(f"{item.get('title')} 未找到季媒体项：{season.get('Id')}")
                        continue

                    if __need_trans_actor(seasoninfo):
                        # 更新季媒体项人物
                        self.__update_peoples(server=server, itemid=season.get("Id"), iteminfo=seasoninfo,
                                              douban_actors=season_actors)
                        self.info(f"季 {seasoninfo.get('Id')} 的人物信息更新完成")
                    else:
                        self.info(f"季 {seasoninfo.get('Id')} 的人物信息已是中文，无需更新")
                # 获取集媒体项
                episodes = self.get_items(server=server, parentid=season.get("Id"), mtype="Episode", service=self)
                if not episodes:
                    self.warn(f"{item.get('title')} 未找到集媒体项")
                    continue
                # 更新集媒体项人物
                for episode in episodes["Items"]:
                    # 获取集媒体项详情
                    episodeinfo = self.get_iteminfo(server=server, itemid=episode.get("Id"), service=self)
                    if not episodeinfo:
                        self.warn(f"{item.get('title')} 未找到集媒体项：{episode.get('Id')}")
                        continue
                    if __need_trans_actor(episodeinfo):
                        # 更新集媒体项人物
                        self.__update_peoples(server=server, itemid=episode.get("Id"), iteminfo=episodeinfo,
                                              douban_actors=season_actors)
                        self.info(f"集 {episodeinfo.get('Id')} 的人物信息更新完成")
                    else:
                        self.info(f"集 {episodeinfo.get('Id')} 的人物信息已是中文，无需更新")

    def __update_people(self, server, people, douban_actors = None):
        """
        更新人物信息，返回替换后的人物信息
        """

        def __get_peopleid(p):
            """
            获取人物的TMDBID、IMDBID
            """
            if not p.get("ProviderIds"):
                return None, None
            peopletmdbid, peopleimdbid = None, None
            if "Tmdb" in p["ProviderIds"]:
                peopletmdbid = p["ProviderIds"]["Tmdb"]
            if "tmdb" in p["ProviderIds"]:
                peopletmdbid = p["ProviderIds"]["tmdb"]
            if "Imdb" in p["ProviderIds"]:
                peopleimdbid = p["ProviderIds"]["Imdb"]
            if "imdb" in p["ProviderIds"]:
                peopleimdbid = p["ProviderIds"]["imdb"]
            return peopletmdbid, peopleimdbid

        # 返回的人物信息
        ret_people = copy.deepcopy(people)

        try:
            # 查询媒体库人物详情
            personinfo = self.get_iteminfo(server=server, itemid=people.get("Id"), service=self)
            if not personinfo:
                self.debug(f"未找到人物 {people.get('Name')} 的信息")
                return None

            # 是否更新标志
            updated_name = False
            updated_overview = False
            update_character = False
            profile_path = None

            # 从TMDB信息中更新人物信息
            person_tmdbid, person_imdbid = __get_peopleid(personinfo)
            if person_tmdbid:
                person_tmdbinfo = self.person_detail(int(person_tmdbid))
                if person_tmdbinfo:
                    cn_name = self.__get_chinese_name(person_tmdbinfo, service=self)
                    if cn_name:
                        # 更新中文名
                        self.debug(f"{people.get('Name')} 从TMDB获取到中文名：{cn_name}")
                        personinfo["Name"] = cn_name
                        ret_people["Name"] = cn_name
                        updated_name = True
                        # 更新中文描述
                        biography = person_tmdbinfo.get("biography")
                        if biography and StringUtils.is_chinese(biography):
                            self.debug(f"{people.get('Name')} 从TMDB获取到中文描述")
                            personinfo["Overview"] = biography
                            updated_overview = True
                        # 图片
                        profile_path = person_tmdbinfo.get('profile_path')
                        if profile_path:
                            self.debug(f"{people.get('Name')} 从TMDB获取到图片：{profile_path}")
                            profile_path = f"{Config().get_config('app').get('tmdb_image_url')}/t/p/original{profile_path}"

            # 从豆瓣信息中更新人物信息
            """
            {
              "name": "丹尼尔·克雷格",
              "roles": [
                "演员",
                "制片人",
                "配音"
              ],
              "title": "丹尼尔·克雷格（同名）英国,英格兰,柴郡,切斯特影视演员",
              "url": "https://movie.douban.com/celebrity/1025175/",
              "user": null,
              "character": "饰 詹姆斯·邦德 James Bond 007",
              "uri": "douban://douban.com/celebrity/1025175?subject_id=27230907",
              "avatar": {
                "large": "https://qnmob3.doubanio.com/view/celebrity/raw/public/p42588.jpg?imageView2/2/q/80/w/600/h/3000/format/webp",
                "normal": "https://qnmob3.doubanio.com/view/celebrity/raw/public/p42588.jpg?imageView2/2/q/80/w/200/h/300/format/webp"
              },
              "sharing_url": "https://www.douban.com/doubanapp/dispatch?uri=/celebrity/1025175/",
              "type": "celebrity",
              "id": "1025175",
              "latin_name": "Daniel Craig"
            }
            """
            if douban_actors and (not updated_name
                                  or not updated_overview
                                  or not update_character):
                # 从豆瓣演员中匹配中文名称、角色和简介
                for douban_actor in douban_actors:
                    if douban_actor.get("latin_name") == people.get("Name") \
                            or douban_actor.get("name") == people.get("Name"):
                        # 名称
                        if not updated_name:
                            self.debug(f"{people.get('Name')} 从豆瓣中获取到中文名：{douban_actor.get('name')}")
                            personinfo["Name"] = douban_actor.get("name")
                            ret_people["Name"] = douban_actor.get("name")
                            updated_name = True
                        # 描述
                        if not updated_overview:
                            if douban_actor.get("title"):
                                self.debug(f"{people.get('Name')} 从豆瓣中获取到中文描述：{douban_actor.get('title')}")
                                personinfo["Overview"] = douban_actor.get("title")
                                updated_overview = True
                        # 饰演角色
                        if not update_character:
                            if douban_actor.get("character"):
                                # "饰 詹姆斯·邦德 James Bond 007"
                                character = re.sub(r"饰\s+", "",
                                                   douban_actor.get("character"))
                                character = re.sub("演员", "",
                                                   character)
                                if character:
                                    self.debug(f"{people.get('Name')} 从豆瓣中获取到饰演角色：{character}")
                                    ret_people["Role"] = character
                                    update_character = True
                        # 图片
                        if not profile_path:
                            avatar = douban_actor.get("avatar") or {}
                            if avatar.get("large"):
                                self.debug(f"{people.get('Name')} 从豆瓣中获取到图片：{avatar.get('large')}")
                                profile_path = avatar.get("large")
                        break

            # 更新人物图片
            if profile_path:
                self.debug(f"更新人物 {people.get('Name')} 的图片：{profile_path}")
                self.set_item_image(server=server, itemid=people.get("Id"), imageurl=profile_path, service=self)

            # 锁定人物信息
            if updated_name:
                if "Name" not in personinfo["LockedFields"]:
                    personinfo["LockedFields"].append("Name")
            if updated_overview:
                if "Overview" not in personinfo["LockedFields"]:
                    personinfo["LockedFields"].append("Overview")

            # 更新人物信息
            if updated_name or updated_overview or update_character:
                self.debug(f"更新人物 {people.get('Name')} 的信息：{personinfo}")
                ret = self.set_iteminfo(server=server, itemid=people.get("Id"), iteminfo=personinfo, service=self)
                if ret:
                    return ret_people
            else:
                self.debug(f"人物 {people.get('Name')} 未找到中文数据")
        except Exception as err:
            self.error(f"更新人物信息失败：{str(err)}")
        return None

    def __get_douban_actors(self, mediainfo, season):
        """
        获取豆瓣演员信息
        """
        # 随机休眠 3-10 秒
        sleep_time = 3 + int(time.time()) % 7
        self.debug(f"随机休眠 {sleep_time}秒 ...")
        time.sleep(sleep_time)
        # 匹配豆瓣信息
        doubaninfo = self.match_doubaninfo(name=mediainfo.title,
                                                 imdbid=mediainfo.imdb_id,
                                                 mtype=mediainfo.type.value,
                                                 year=mediainfo.year,
                                                 season=season)
        # 豆瓣演员
        if doubaninfo:
            doubanitem = self.douban.get_douban_detail(doubanid=doubaninfo.get("id"), mtype=None, wait=False) or {}
            # doubanitem = WebUtils.get_mediainfo_from_id(mediaid="DB:" + doubaninfo.get("id"), mtype="") or {}
            return (doubanitem.get("actors") or []) + (doubanitem.get("directors") or [])
        else:
            self.debug(f"未找到豆瓣信息：{mediainfo.title_year}")
        return []

    @staticmethod
    def get_iteminfo(server, itemid, service):
        """
        获得媒体项详情
        """

        def __get_emby_iteminfo():
            """
            获得Emby媒体项详情
            """
            try:
                url = f'[HOST]/emby/Users/[USER]/Items/{itemid}?' \
                      f'Fields=ChannelMappingInfo&api_key=[APIKEY]'
                res = service.get_data(url=url)
                if res:
                    return res.json()
            except Exception as err:
                service.error(f"获取Emby媒体项详情失败：{str(err)}")
            return {}

        def __get_jellyfin_iteminfo():
            """
            获得Jellyfin媒体项详情
            """
            try:
                url = f'[HOST]/Users/[USER]/Items/{itemid}?Fields=ChannelMappingInfo&api_key=[APIKEY]'
                res = service.get_data(url=url)
                if res:
                    result = res.json()
                    if result:
                        result['FileName'] = Path(result['Path']).name
                    return result
            except Exception as err:
                service.error(f"获取Jellyfin媒体项详情失败：{str(err)}")
            return {}

        def __get_plex_iteminfo():
            """
            获得Plex媒体项详情
            """
            iteminfo = {}
            try:
                plexitem = service.mschain.fetchItem(ekey=itemid)
                if 'movie' in plexitem.METADATA_TYPE:
                    iteminfo['Type'] = 'Movie'
                    iteminfo['IsFolder'] = False
                elif 'episode' in plexitem.METADATA_TYPE:
                    iteminfo['Type'] = 'Series'
                    iteminfo['IsFolder'] = False
                    if 'show' in plexitem.TYPE:
                        iteminfo['ChildCount'] = plexitem.childCount
                iteminfo['Name'] = plexitem.title
                iteminfo['Id'] = plexitem.key
                iteminfo['ProductionYear'] = plexitem.year
                iteminfo['ProviderIds'] = {}
                for guid in plexitem.guids:
                    idlist = str(guid.id).split(sep='://')
                    if len(idlist) < 2:
                        continue
                    iteminfo['ProviderIds'][idlist[0]] = idlist[1]
                for location in plexitem.locations:
                    iteminfo['Path'] = location
                    iteminfo['FileName'] = Path(location).name
                iteminfo['Overview'] = plexitem.summary
                iteminfo['CommunityRating'] = plexitem.audienceRating
                return iteminfo
            except Exception as err:
                service.error(f"获取Plex媒体项详情失败：{str(err)}")
            return {}

        if server == "emby":
            return __get_emby_iteminfo()
        elif server == "jellyfin":
            return __get_jellyfin_iteminfo()
        else:
            return __get_plex_iteminfo()

    @staticmethod
    def get_items(server, parentid, mtype, service):
        """
        获得媒体的所有子媒体项
        """
        pass

        def __get_emby_items() -> dict:
            """
            获得Emby媒体的所有子媒体项
            """
            try:
                if parentid:
                    url = f'[HOST]/emby/Users/[USER]/Items?ParentId={parentid}&api_key=[APIKEY]'
                else:
                    url = '[HOST]/emby/Users/[USER]/Items?api_key=[APIKEY]'
                res = service.get_data(url=url)
                if res:
                    return res.json()
            except Exception as err:
                service.error(f"获取Emby媒体的所有子媒体项失败：{str(err)}")
            return {}

        def __get_jellyfin_items():
            """
            获得Jellyfin媒体的所有子媒体项
            """
            try:
                if parentid:
                    url = f'[HOST]/Users/[USER]/Items?ParentId={parentid}&api_key=[APIKEY]'
                else:
                    url = '[HOST]/Users/[USER]/Items?api_key=[APIKEY]'
                res = service.get_data(url=url)
                if res:
                    return res.json()
            except Exception as err:
                service.error(f"获取Jellyfin媒体的所有子媒体项失败：{str(err)}")
            return {}

        def __get_plex_items():
            """
            获得Plex媒体的所有子媒体项
            """
            items = {}
            try:
                items['Items'] = []
                if parentid:
                    if mtype and 'Season' in mtype:
                        plexitem = service.mschain.fetchItem(ekey=parentid)
                        items['Items'] = []
                        for season in plexitem.seasons():
                            item = {
                                'Name': season.title,
                                'Id': season.key,
                                'IndexNumber': season.seasonNumber,
                                'Overview': season.summary
                            }
                            items['Items'].append(item)
                    elif mtype and 'Episode' in mtype:
                        plexitem = service.mschain.fetchItem(ekey=parentid)
                        items['Items'] = []
                        for episode in plexitem.episodes():
                            item = {
                                'Name': episode.title,
                                'Id': episode.key,
                                'IndexNumber': episode.episodeNumber,
                                'Overview': episode.summary,
                                'CommunityRating': episode.audienceRating
                            }
                            items['Items'].append(item)
                    else:
                        plexitems = service.mschain.sectionByID(sectionID=parentid)
                        for plexitem in plexitems.all():
                            item = {}
                            if 'movie' in plexitem.METADATA_TYPE:
                                item['Type'] = 'Movie'
                                item['IsFolder'] = False
                            elif 'episode' in plexitem.METADATA_TYPE:
                                item['Type'] = 'Series'
                                item['IsFolder'] = False
                            item['Name'] = plexitem.title
                            item['Id'] = plexitem.key
                            items['Items'].append(item)
                else:
                    plexitems = service.mschain.sections()
                    for plexitem in plexitems:
                        item = {}
                        if 'Directory' in plexitem.TAG:
                            item['Type'] = 'Folder'
                            item['IsFolder'] = True
                        elif 'movie' in plexitem.METADATA_TYPE:
                            item['Type'] = 'Movie'
                            item['IsFolder'] = False
                        elif 'episode' in plexitem.METADATA_TYPE:
                            item['Type'] = 'Series'
                            item['IsFolder'] = False
                        item['Name'] = plexitem.title
                        item['Id'] = plexitem.key
                        items['Items'].append(item)
                return items
            except Exception as err:
                service.error(f"获取Plex媒体的所有子媒体项失败：{str(err)}")
            return {}

        if server == "emby":
            return __get_emby_items()
        elif server == "jellyfin":
            return __get_jellyfin_items()
        else:
            return __get_plex_items()

    @staticmethod
    def set_iteminfo(server, itemid, iteminfo, service):
        """
        更新媒体项详情
        """

        def __set_emby_iteminfo():
            """
            更新Emby媒体项详情
            """
            try:
                res = service.post_data(
                    url=f'{service._host}/emby/Items/{itemid}?api_key={service._apikey}&reqformat=json',
                    data=json.dumps(iteminfo),
                    headers={
                        "Content-Type": "application/json"
                    }
                )
                if res and res.status_code in [200, 204]:
                    return True
                else:
                    service.error(f"更新Emby媒体项详情失败，错误码：{res.status_code}")
                    return False
            except Exception as err:
                service.error(f"更新Emby媒体项详情失败：{str(err)}")
            return False

        def __set_jellyfin_iteminfo():
            """
            更新Jellyfin媒体项详情
            """
            try:
                res = service.post_data(
                    url=f'{service._host}/Items/{itemid}?api_key={service._apikey}',
                    data=json.dumps(iteminfo),
                    headers={
                        "Content-Type": "application/json"
                    }
                )
                if res and res.status_code in [200, 204]:
                    return True
                else:
                    service.error(f"更新Jellyfin媒体项详情失败，错误码：{res.status_code}")
                    return False
            except Exception as err:
                service.error(f"更新Jellyfin媒体项详情失败：{str(err)}")
            return False

        def __set_plex_iteminfo():
            """
            更新Plex媒体项详情
            """
            try:
                plexitem = service.mschain.fetchItem(ekey=itemid)
                if 'CommunityRating' in iteminfo:
                    edits = {
                        'audienceRating.value': iteminfo['CommunityRating'],
                        'audienceRating.locked': 1
                    }
                    plexitem.edit(**edits)
                plexitem.editTitle(iteminfo['Name']).editSummary(iteminfo['Overview']).reload()
                return True
            except Exception as err:
                service.error(f"更新Plex媒体项详情失败：{str(err)}")
            return False

        if server == "emby":
            return __set_emby_iteminfo()
        elif server == "jellyfin":
            return __set_jellyfin_iteminfo()
        else:
            return __set_plex_iteminfo()

    @staticmethod
    @retry(RequestException)
    def set_item_image(server, itemid, imageurl, service=None):
        """
        更新媒体项图片
        """

        def __download_image():
            """
            下载图片
            """
            try:
                if "doubanio.com" in imageurl:
                    headers = {
                        'Referer': "https://movie.douban.com/",
                        'User-Agent': choice(service._user_agents)
                    }
                    r = RequestUtils(headers=headers).get_res(url=imageurl, raise_exception=True)
                else:
                    r = RequestUtils().get_res(url=imageurl, raise_exception=True)
                if r:
                    return base64.b64encode(r.content).decode()
                else:
                    service.warn(f"{imageurl} 图片下载失败，请检查网络连通性")
            except Exception as err:
                service.error(f"下载图片失败：{str(err)}")
            return None

        def __set_emby_item_image(_base64):
            """
            更新Emby媒体项图片
            """
            try:
                url = f'{service._host}/emby/Items/{itemid}/Images/Primary?api_key={service._apikey}'
                res = service.post_data(
                    url=url,
                    data=_base64,
                    headers={
                        "Content-Type": "image/png"
                    }
                )
                if res and res.status_code in [200, 204]:
                    return True
                else:
                    service.error(f"更新Emby媒体项图片失败，错误码：{res.status_code}")
                    return False
            except Exception as result:
                service.error(f"更新Emby媒体项图片失败：{result}")
            return False

        def __set_jellyfin_item_image():
            """
            更新Jellyfin媒体项图片
            # FIXME 改为预下载图片
            """
            try:
                url = f'{service._host}/Items/{itemid}/RemoteImages/Download?' \
                      f'Type=Primary&ImageUrl={imageurl}&ProviderName=TheMovieDb&api_key={service._apikey}'
                res = service.post_data(url=url)
                if res and res.status_code in [200, 204]:
                    return True
                else:
                    service.error(f"更新Jellyfin媒体项图片失败，错误码：{res.status_code}")
                    return False
            except Exception as err:
                service.error(f"更新Jellyfin媒体项图片失败：{err}")
            return False

        def __set_plex_item_image():
            """
            更新Plex媒体项图片
            # FIXME 改为预下载图片
            """
            try:
                plexitem = service.mschain.fetchItem(ekey=itemid)
                plexitem.uploadPoster(url=imageurl)
                return True
            except Exception as err:
                service.error(f"更新Plex媒体项图片失败：{err}")
            return False

        if server == "emby":
            # 下载图片获取base64
            image_base64 = __download_image()
            if image_base64:
                return __set_emby_item_image(image_base64)
        elif server == "jellyfin":
            return __set_jellyfin_item_image()
        else:
            return __set_plex_item_image()
        return None

    @staticmethod
    def __get_chinese_name(personinfo, service=None):
        """
        获取TMDB别名中的中文名
        """
        try:
            also_known_as = personinfo.get("also_known_as") or []
            if also_known_as:
                for name in also_known_as:
                    if name and StringUtils.is_chinese(name):
                        # 使用cn2an将繁体转化为简体
                        return zhconv.convert(name, "zh-hans")
        except Exception as err:
            service.error(f"获取人物中文名失败：{err}")
        return ""

    @staticmethod
    @lru_cache(maxsize=512)
    def cached_request(method, url, data, proxies):
        return requests.request(method, url, data=data, proxies=eval(proxies), verify=False, timeout=10)

    def _call(
            self, action, append_to_response, call_cached=True, method="GET", data=None
    ):
        if self.tmdb.api_key is None or self.tmdb.api_key == "":
            raise TMDbException("No API key found.")

        url = "%s%s?api_key=%s&include_adult=false&%s&language=%s" % (
            self.tmdb.domain,
            action,
            self.tmdb.api_key,
            append_to_response,
            self.tmdb.language,
        )

        if self.tmdb.cache and self.tmdb.obj_cached and call_cached and method != "POST":
            req = self.cached_request(method, url, data, self.tmdb.proxies)
        else:
            req = self._session.request(method, url, data=data, proxies=eval(self.tmdb.proxies), timeout=10, verify=False)

        headers = req.headers

        if "X-RateLimit-Remaining" in headers:
            self._remaining = int(headers["X-RateLimit-Remaining"])

        if "X-RateLimit-Reset" in headers:
            self._reset = int(headers["X-RateLimit-Reset"])

        if self._remaining < 1:
            current_time = int(time.time())
            sleep_time = self._reset - current_time

            if self.wait_on_rate_limit:
                self.warning("Rate limit reached. Sleeping for: %d" % sleep_time)
                time.sleep(abs(sleep_time))
                self._call(action, append_to_response, call_cached, method, data)
            else:
                raise TMDbException(
                    "Rate limit reached. Try again in %d seconds." % sleep_time
                )

        json = req.json()

        if "page" in json:
            os.environ["page"] = str(json["page"])

        if "total_results" in json:
            os.environ["total_results"] = str(json["total_results"])

        if "total_pages" in json:
            os.environ["total_pages"] = str(json["total_pages"])

        if self.debug:
            self.info(json)
            self.info(self.cached_request.cache_info())

        if "errors" in json:
            raise TMDbException(json["errors"])

        return json

    def person_detail(self, movie_id, append_to_response="videos,images"):
        return AsObj(
            **self._call(
                f"/person/{movie_id}",
                "append_to_response=" + append_to_response,
            )
        )

    def get_data(self, url):
        """
        自定义URL从媒体服务器获取数据，其中[HOST]、[APIKEY]、[USER]会被替换成实际的值
        :param url: 请求地址
        """
        if not self._host or not self._apikey:
            return None
        url = url.replace("[HOST]", self._host) \
            .replace("[APIKEY]", self._apikey) \
            .replace("[USER]", self._user)
        try:
            return RequestUtils(content_type="application/json").get_res(url=url)
        except Exception as e:
            self.error(f"连接媒体服务器出错：" + str(e))
            return None

    def get_user(self, user_name=None):
        """
        获得管理员用户
        """
        if not self._host or not self._apikey:
            return None
        req_url = "%s/Users?api_key=%s" % (self._host, self._apikey)
        try:
            res = RequestUtils().get_res(req_url)
            if res:
                users = res.json()
                # 先查询是否有与当前用户名称匹配的
                if user_name:
                    for user in users:
                        if user.get("Name") == user_name:
                            return user.get("Id")
                # 查询管理员
                for user in users:
                    if user.get("Policy", {}).get("IsAdministrator"):
                        return user.get("Id")
            else:
                self.error(f"【媒体服务】Users 未获取到返回数据")
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            self.error(f"【媒体服务】连接Users出错：" + str(e))
        return None

    def post_data(self, url: str, data: str = None, headers: dict = None):
        """
        自定义URL从媒体服务器获取数据，其中[HOST]、[APIKEY]、[USER]会被替换成实际的值
        :param url: 请求地址
        :param data: 请求数据
        :param headers: 请求头
        """
        if not self._host or not self._apikey:
            return None
        url = url.replace("[HOST]", self._host) \
            .replace("[APIKEY]", self._apikey) \
            .replace("[USER]", self._user)
        try:
            return RequestUtils(
                headers=headers,
            ).post_res(url=url, data=data)
        except Exception as e:
            self.error(f"连接Emby出错：" + str(e))
            return None

    @retry(Exception, 5, 3, 3)
    def match_doubaninfo(self, name: str, imdbid: str = None,
                         mtype: str = None, year: str = None, season: int = None):
        """
        搜索和匹配豆瓣信息
        :param name:  名称
        :param imdbid:  IMDB ID
        :param mtype:  类型 电影/电视剧
        :param year:  年份
        :param season:  季号
        """
        if imdbid:
            # 优先使用IMDBID查询
            self.info(f"开始使用IMDBID {imdbid} 查询豆瓣信息 ...")
            result = self.douban_imdbid(imdbid=imdbid)
            self.info(f"开始使用IMDBID搜索结果 {result}")
            if result:
                doubanid = result.get("id")
                if doubanid and not str(doubanid).isdigit():
                    doubanid = re.search(r"\d+", doubanid).group(0)
                    result["id"] = doubanid
                self.info(f"{imdbid} 查询到豆瓣信息：{result.get('title')}")
                return result
        # 搜索
        self.info(f"开始使用名称 {name} 匹配豆瓣信息 ...")
        result = self.doubanapi.search(f"{name} {year or ''}".strip())
        if not result:
            self.warn(f"未找到 {name} 的豆瓣信息")
            return {}
        # 触发rate limit
        if "search_access_rate_limit" in result.values():
            self.warn(f"触发豆瓣API速率限制 错误信息 {result} ...")
            raise Exception("触发豆瓣API速率限制")
        for item_obj in result.get("items"):
            type_name = item_obj.get("type_name")
            if type_name not in [MediaType.TV.value, MediaType.MOVIE.value]:
                continue
            if mtype and mtype != type_name:
                continue
            if mtype == MediaType.TV and not season:
                season = 1
            item = item_obj.get("target")
            title = item.get("title")
            if not title:
                continue
            meta = MetaInfo(title)
            if type_name == MediaType.TV.value:
                meta.type = MediaType.TV
                meta.begin_season = meta.begin_season or 1
            if meta.name == name \
                    and ((not season and not meta.begin_season) or meta.begin_season == season) \
                    and (not year or item.get('year') == year):
                self.info(f"{name} 匹配到豆瓣信息：{item.get('id')} {item.get('title')}")
                return item
        return {}

    @lru_cache(maxsize=512)
    def douban_imdbid(self, imdbid):
        req_url = "https://api.douban.com/v2/movie/imdb/" + imdbid
        params = {'apikey': "0ab215a8b1977939201640fa14c66bab"}
        if '_ts' in params:
            params.pop('_ts')
        headers = {'User-Agent': choice(self._user_agents)}
        resp = RequestUtils(headers=headers, session=self._session).post_res(url=req_url, data=params)
        if resp.status_code == 400 and "rate_limit" in resp.text:
            return resp.json()
        return resp.json() if resp else {}