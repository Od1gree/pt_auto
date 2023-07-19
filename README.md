免责声明：脚本开发时间有限，难免有bug存在，若试用后账号被ban，概不负责。
# PT网站刷魔力脚本
脚本在遵守网站规则的前提下，结合本人实际需求，实现自动化刷上传数据的能力。
此脚本在`ubuntu20.04`、`python3.11`、`qbittorrent-api==2023.6.50`、docker镜像`linuxserver/qbittorrent:4.4.5`环境中测试通过

## 功能
* 用户自定义种子存储位置
* 过滤时间过久、体积过大的种子
* 保证HR最低限制要求
* 上传活跃的种子能够根据情况保留较长时间后再删除
* 根据传输列表状态，弹性化rss订阅刷新周期，减小服务器负载
* 密码从环境变量读取，保护隐私；同时兼容代码中明文填写密码

## 脚本的使用
### 执行环境
* 操作系统：推荐linux，理论上在Windows上也能用。
* `python >= 3.8`

### python第三方依赖安装
`python -m pip install qbittorrent-api`

### 程序执行
* `python main.py`

## 脚本的修改
以下是大致逻辑信息，可供参考

### 脚本执行逻辑
1. 刷新当前磁盘剩余空间、下载列表、rss链接内容
2. `check_deletion`检查是否有可删除的种子文件，默认删除判定使用`JUDGER_DELETE_FAST_FLOW`对应的`_judger_fastflow`函数。
    * 再次刷新剩余磁盘空间
3. `check_addition`检查是否有可以从rss添加的文件，默认添加使用`JUDGER_ADD_NEAREST_ONE`对应的`_judger_nearestone`函数。
4. 等待一定时间，重新执行第一步。

### 类描述
* `Monitor`：用于执行整个监控循环，并于qbittorrent api进行通信
* `Job`：用于表示下载列表的一项
* `Torrent`：用于表示rss订阅列表中的一项。