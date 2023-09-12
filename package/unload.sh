#!/bin/bash

# 临时目录
TMP_PATH=/tmp/nas-tools
# 套件目录
KIT_PATH=/var/packages/NASTool/target
# 修复包的下载地址
WODNLOAD_URL=https://raw.githubusercontent.com/Mattoids/nas-tools-plugin/master/package/nas-tools.tar

# 清理临时目录
clone_tmp() {
	echo "清理临时目录"
	rm -rf $TMP_PATH
}

# 下载修复文件
download_file() {
	# 创建临时目录
	mkdir -p $TMP_PATH
	
	echo "下载文件..."
	curl -o "$TMP_PATH/nas-tools.tar" $WODNLOAD_URL
}

# 解压文件
unzip_file() {
    echo "解压文件到临时目录"
	  tar -xf "$TMP_PATH/nas-tools.tar" -C $TMP_PATH
    if [ ! -d "$TMP_PATH/nas-tools" ]; then
        echo "解压失败，终止任务！"
        exit 1
    fi
}

kit_unload() {
	echo "开始卸载插件..."
	cp -R $TMP_PATH/nas-tools $KIT_PATH
	chmod -R 777 $KIT_PATH/nas-tools
	chown -R NASTool:NASTool $KIT_PATH/nas-tools
	echo "插件卸载成功，请去套件中心重启套件！"
}

# Docker容器内部处理
dockershell_unload() {
  KIT_PATH=/

	# 获取 nas-tools 的版本信息
	if [ ! -e "/nas-tools/version.py" ]; then
		echo "未找到您的套件，请确认套件已正确安装在您的DSM系统中！"
	    exit 1
	fi
	NASTOOL_VERSION=$(cat "/nas-tools/version.py" | awk '{ print $3 }' | sed "s/'//g" | sed 's/v//g')
	if [ -z $NASTOOL_VERSION ]; then
	    echo "未找到您的套件，请确认套件已正确安装在您的DSM系统中！"
	    exit 1
	fi

	# 下载并解压修复包
	download_file
	unzip_file

  echo "开始卸载插件..."
	cp -R $TMP_PATH/nas-tools $KIT_PATH
	chmod -R 777 $KIT_PATH/nas-tools
  chown -R root:root $KIT_PATH/nas-tools
	echo "插件卸载成功，请重启docker容器哦！"
}

# 处理Docker
docker_unload() {
	echo "开始处理 Docker 容器..."
	WAIT_DOCKER_IDS=()
	
	# 获取所有已启动的 nas-tools 镜像生成的容器
	NASTOOL_IDS=$(docker ps --format "{{.ID}} {{.Image}}" | egrep "nas-tools|nas-tool|nastools|nastool" | awk '{ print $1 }')
	
	for NASTOOL_ID in $NASTOOL_IDS
	do
		echo "检查容器 $NASTOOL_ID 是否合法"
		# 获取 nas-tools 的版本信息
		NASTOOL_VERSION=$(docker exec $NASTOOL_ID cat version.py | awk '{ print $3 }' | sed "s/'//g" | sed 's/v//g')
		if [ -z $NASTOOL_VERSION ]; then
			echo "容器 $NASTOOL_ID 不合法，请先停止该容器后再执行命令"
			exit 1
		fi
		# 获取版本大于3.0的容器ID
		if [ -n $NASTOOL_VERSION ]; then
			WAIT_DOCKER_IDS[${#WAIT_DOCKER_IDS[*]}]=$NASTOOL_ID
		fi
	done

	# 是否有符合条件的 nas-tools 容器
	if [ -n WAIT_DOCKER_IDS ] && [ ${#WAIT_DOCKER_IDS[*]} -eq 0 ] ; then
		echo "没有找到 nas-tools 容器"
		exit 1
	fi
	if [ -n WAIT_DOCKER_IDS ] && [ ${#WAIT_DOCKER_IDS[*]} -gt 0 ]; then
		echo "找到 ${#WAIT_DOCKER_IDS[*]}个容器"
	fi
	echo "开始安装插件！"

	download_file
	unzip_file

	for DOCKER_ID in ${WAIT_DOCKER_IDS[*]}
	do
		echo "容器：$DOCKER_ID 开始处理..."
		docker cp -a "$TMP_PATH/nas-tools" $DOCKER_ID:/
		echo "容器：$DOCKER_ID 重启中..."
		docker stop $DOCKER_ID
		echo "容器：$DOCKER_ID 正在启动..."
		docker start $DOCKER_ID
		echo "容器：$DOCKER_ID 卸载完成!"
	done

}

dsm7_install() {
    KIT_PATH=/var/packages/NASTool/target

	# 获取 nas-tools 的版本信息
	if [ ! -e "$KIT_PATH/nas-tools/version.py" ]; then
		echo "未找到您的套件，请确认套件已正确安装在您的DSM系统中！"
	    exit 1
	fi
	NASTOOL_VERSION=$(cat "$KIT_PATH/nas-tools/version.py" | awk '{ print $3 }' | sed "s/'//g" | sed 's/v//g')
	if [ -z $NASTOOL_VERSION ]; then
	    echo "未找到您的套件，请确认套件已正确安装在您的DSM系统中！"
	    exit 1
	fi

# 下载并解压修复包
	download_file
	unzip_file

  chmod -R 777 $KIT_PATH/config/plugins
	chown -R NASTool:NASTool $KIT_PATH/config/plugins

	# 检查套件版本
	if [ -n $NASTOOL_VERSION ]; then
	  echo "套件版本不要符合安装要求，不支持安装！"
		exit 1
	fi

	kit_unload
}

dsm6_unload() {
    KIT_PATH=/var/packages/NASTool/target

	# 获取 nas-tools 的版本信息
	if [ ! -e "$KIT_PATH/nas-tools/version.py" ]; then
		echo "未找到您的套件，请确认套件已正确安装在您的DSM系统中！"
	    exit 1
	fi
	NASTOOL_VERSION=$(cat "$KIT_PATH/nas-tools/version.py" | awk '{ print $3 }' | sed "s/'//g" | sed 's/v//g')
	if [ -z $NASTOOL_VERSION ]; then
	    echo "未找到您的套件，请确认套件已正确安装在您的DSM系统中！"
	    exit 1
	fi

	# 下载并解压修复包
	download_file
	unzip_file

  chmod -R 777 $KIT_PATH/config/plugins
	chown -R NASTool:NASTool $KIT_PATH/config/plugins

	# 检查套件版本
	NASTOOL_VERSION=$(cat "$KIT_PATH/nas-tools/version.py" | awk '{ print $3 }' | sed "s/'//g" | sed 's/v//g')
	if [ -z $NASTOOL_VERSION ]; then
	    echo "未找到您的套件，请确认套件已正确安装在您的DSM系统中！"
	    exit 1
	fi

  kit_unload
}



if [ -z "$1" ]; then
	echo "请输入要操作的类型"
	exit 1
fi

# 开始执行脚本
eval "$1_unload"
clone_tmp
