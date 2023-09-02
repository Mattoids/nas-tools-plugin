# 第三方插件商店拓展包
- 后续更新将通过系统内部的更新检测功能从 [mattoids/nas-tools](https://github.com/Mattoids/nas-tools) 仓库拉取
- 该仓库后续仅提供插件安装和更新服务，不在提供系统级别的更新


## 目录介绍
~~~
.
├── logo                        # nastool的logo
├── package
│   ├── install.sh              # 一键安装脚本
│   └── nas-tools-plugin.tar    # 拓展更新包
├── plugins                     # 新增插件
│   ├── images                  # 插件对应的图片
├── sites                       # 站点规则目录（用于自定义索引器配置索引规则）
│   ├── brush                   # 刷流规则（不配置的话刷流页面站点无法选择免费种子）  
├── README.md                   # 说明文件
└── source.json                 # 源地址配置

~~~

## 安装方法

根据系统执行对应的命令即可，`需要root权限`执行。
也可下载 `shell` 脚本，从脚本内提取安装包，自行替换 `nas-tools` 目录

### docker shell（容器内部执行）
~~~shell
bash <(curl -s https://github.com/Mattoids/nas-tools-plugin/raw/master/package/install.sh) dockershell
~~~

### docker（容器外部执行）
~~~shell
bash <(curl -s https://github.com/Mattoids/nas-tools-plugin/raw/master/package/install.sh) docker
~~~

### dsm7
~~~shell
bash <(curl -s https://github.com/Mattoids/nas-tools-plugin/raw/master/package/install.sh) dsm7
~~~

### dsm6
~~~shell
bash <(curl -s https://github.com/Mattoids/nas-tools-plugin/raw/master/package/install.sh) dsm6
~~~

### 脚本运行报错的时候尝试下面的命令
~~~
curl -O https://github.com/Mattoids/nas-tools-plugin/raw/master/package/install.sh && chmod 655 install.sh && ./install.sh docker
~~~

## 第三方源
~~~
https://github.com/Mattoids/nas-tools-plugin/raw/master/source.json
~~~

# 图文说明

### 第一步、打开第三方插件商店
![打开第三方插件商店](https://github.com/Mattoids/nas-tools-plugin/raw/master/images/1.png)

### 第二步、进入商店设置页面
![进入商店设置页面](https://github.com/Mattoids/nas-tools-plugin/raw/master/images/2.png)

### 第三步、添加第三方插件源
![添加第三方插件源](https://github.com/Mattoids/nas-tools-plugin/raw/master/images/3.png)

```
完成以上操作以后，关闭第三方插件页面，重新打开即可看到插件，安装即可
```

# 插件使用说明

### 添加站点规则
### `这里的【站点域名】需要和站点里的【站点地址】配置一致`
![站点设置](https://github.com/Mattoids/nas-tools-plugin/raw/master/images/site.png)
```
填写 站点域名 + 原始域名
站点索引规则 为空
```
![替换旧的站点域名](https://github.com/Mattoids/nas-tools-plugin/raw/master/images/indexer.png)

### 打开 json 格式化网址
<https://www.bejson.com/>
~~~
1. 复制上一步输入框的内容
2. 打开解析站点
3. 粘贴到网站中点【格式化校验】和【Unicode转中文】，修改name为你添加的站点的中文名（随便写也没关系）
4. 点击 【压缩】和【中文转Unicode】，然后复制站点里面的内容
5. 粘贴回上一步的框中（把原有的删除以后再粘贴）
6. 保存
7. 你可以去索引器里面找你的站点了
~~~
![bejson](https://github.com/Mattoids/nas-tools-plugin/raw/master/images/bejson.png)
