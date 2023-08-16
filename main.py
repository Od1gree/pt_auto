import qbittorrentapi as qb
from collections.abc import Callable
import time
import datetime
import signal
from datetime import datetime
import re
import math
import logging
import shutil
import platform
import os

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
log_format = logging.Formatter('%(asctime)s - %(levelname)s %(filename)s:%(lineno)d %(message)s')
fh = logging.FileHandler(filename=f"log{datetime.now().strftime(r'%Y-%m-%d')}.log", encoding="utf-8")
fh.setLevel(logging.INFO)
fh.setFormatter(log_format)

sh = logging.StreamHandler()
sh.setLevel(logging.DEBUG)
sh.setFormatter(log_format)

logger.addHandler(fh)
logger.addHandler(sh)





class Torrent(object):
    DATE_FORMAT = r"%d %b %Y %H:%M:%S %z"
    FILE_SIZE_PATTERN = re.compile(r"\[(\d+\.\d+ TB|\d+\.\d+ GB|\d+\.\d+ MB|\d+\.\d+ KB|\d+\.\d+ B)\]$")
    def __init__(self, article_item=None):
        """
        article_item: single article in dict format.
        """
        self.release_datetime = datetime.strptime(article_item["date"], Torrent.DATE_FORMAT)
        self.filesize = self._get_size(Torrent.FILE_SIZE_PATTERN.findall(article_item["title"])[0])
        self.link = article_item["torrentURL"]
        logger.debug(f"init title={article_item['title']}, time={article_item['date']}, time={self.release_datetime}, size={self.filesize}")
    
    def _get_size(self, size_str:str)->int:
        """
        given file size in string,
        return actual size as integer.
        return -1 if error occured
        """
        if len(size_str)==0:
            logger.error("length of size_str is 0")
            return -1
        measure = size_str[-2:]
        value_f = float(size_str.split(" ")[0])

        if measure[1]!="B":
            logger.error(f"size_str measurement not end with B, size_str={size_str}")
            return -1

        if measure[0]=='T':
            return int(value_f * math.pow(1024,4))
        elif measure[0]=='G':
            return int(value_f * math.pow(1024,3))
        elif measure[0]=='M':
            return int(value_f * math.pow(1024,2))
        elif measure[0]=='K':
            return int(value_f * 1024)
        elif measure[0]==' ':
            return value_f
        else:
            logger.warning(f"unexpected size_str:{size_str}")
            return -1
    
    def __eq__(self, __value: object) -> bool:
        return self.release_datetime == __value.release_datetime

    def __lt__(self, __value: object) -> bool:
        return self.release_datetime < __value.release_datetime
        
class Job(object):
    """
    A Job class represents a single download job.
    Hold parameters parse from api.
    """
    def __init__(self, job_dict:dict=None):
        self.is_init = 0
        self.added_on = 0  # unix timestamp on start
        self.amount_left = 0  # bytes left
        self.completion_on = 0  # unix timestamp on completion
        self.hash = '' 
        self.last_activity = 0  # unix timestamp on last download/upload
        self.ratio = -1 # share ratio in float
        self.seeding_time = 0  # time in secs after complete'
        self.size = 0  # selected file size
        self.tags = ''
        self.name = ''
        self.progress = -1
        self.uploaded = 0
        if job_dict is None:
            logger.error("Job init from None object")
        else:
            for k in job_dict:
                setattr(self, k, job_dict[k])
        
        self.upload_delta = 0
    
    def calc_upload_delta(self, old_up_amount: int):
        """
        TODO: calc upload size delta to help deletion judgement
        """
        pass


class Monitor(object):
    """
    Monitor class hold all job and determine whether
    """
    # delete preset
    JUDGER_DELETE_FAST_FLOW = 1

    # add preset
    JUDGER_ADD_NEAREST_ONE = 1
    def __init__(self, refresh_min: int=5, storage_auto_limit: int=None, storage_path: str=None, download_path: str=None,
                 storage_total_limit: int=None, min_seed_sec: int=21*60*60, min_up_ratio: float=1.1,
                 raw_run: bool=False, storage_free_threshold: float=1, tag_name: str="auto", qb_host: str=None,
                 qb_port: int=8080, qb_username: int=None, qb_pw: int=None):
        """
        refresh_min: rss refresh interval in minute.
        storage_auto_limit: size of auto tagged torrent files in GB. 
                            If set to None, the monitor will use disk free space as only threshold.
        storage_total_limit: total size of all torrent files in qbittorren list in GB.
                            This parameter is used to increase reliability of checking disk free space,
                            in case some torrent files are not pre-allocated during downloading.
        storage_path: path of torrent files. Monitor use storage_path to check real free disk space.
        download_path: path of torrent files saving. useful when qbittorrent is deployed in docker.
        min_seed_sec: minimum seeding time in seconds.
        min_up_ratio: minimun upload ratio.
        raw_run: True for testing, will run code and not change any status of torrents.
        storage_free_threshold: system free space serve limit in GB
        tag_name: torrent tag of auto downloaded torrents
        qb_host: host ip of qbittorrent-web
        qb_port: port of qbittorrent-web
        qb_username: username of qbittorrent-web
        qb_pw: password of qbittorrent-web
        """
        self.job_list: list[Job] = []
        self.storage_path: str = None  # init later
        self.download_path: str = download_path
        self.auto_list: list[Job] = []
        self.rss_list: list[Torrent] = []
        self.disk_free: int = 0  # global disk free
        self.storage_auto_free: int = 0  # free space for torrents managed by self. None if storage_auto_limit is None
        self.storage_auto_limit = storage_auto_limit * math.pow(1024, 3)
        self.storage_total_limit = storage_total_limit * math.pow(1024, 3)
        self.min_up_ratio = min_up_ratio
        self.min_seed_sec = min_seed_sec
        self.raw_run = raw_run
        self.refresh_sec = refresh_min * 60
        self.storage_free_threshold = storage_free_threshold * math.pow(1024, 3)
        self.tag_name = tag_name
        self.next_refresh_delay = 0

        self.client = qb.Client(host=qb_host,port=qb_port,username=qb_username,password=qb_pw)
        self.client.auth_log_in()
        

        if storage_path is None:
            cur_platform = platform.system()
            logger.debug(f"Platform detect result: {cur_platform}")
            if cur_platform == "Windows":
                self.storage_path = 'C:\\'
            elif (cur_platform == 'Linux') or (cur_platform == 'Darwin'):
                self.storage_path = '/'
            else:
                logger.warning("Can not determine platform, storage_path set to / by default")
                self.storage_path = '/'
        else:
            self.storage_path = storage_path
        
    def start(self):
        while True:
            try:
                self.update_job_list()
                self.update_free_space()

                while True:
                    self.update_job_list()
                    self.check_deletion()
                    time.sleep(10)
                    self.update_job_list()
                    self.update_free_space()
                    self.check_addition()
                    time.sleep(self.refresh_sec - 10 + self._judger_next_delay())
            except Exception as e:
                logger.error(f"caught error: {e=}, {type(e)=}")
                time.sleep(300)



    def update_job_list(self):
        """
        request api to update job_list
        """
        self.job_list = []
        self.auto_list = []
        torrent_list = self.client.torrents.info()
        for torrent in torrent_list:
            cur_job = Job(torrent)
            self.job_list.append(cur_job)
            if cur_job.tags == 'auto':
                self.auto_list.append(cur_job)
    
    def update_free_space(self):
        # update disk_free
        # if storage_total_limit is set, compare and choose smaller one: storage_total_free && disk_free
        if self.storage_total_limit is not None:
            system_free = shutil.disk_usage(self.storage_path).free
            total_storage_usage = 0
            for job in self.job_list:
                total_storage_usage += job.size
            total_storage_free = self.storage_total_limit - total_storage_usage
            if 0 < system_free < self.storage_free_threshold:
                logger.info(f"system free space {system_free} < threshold {self.storage_free_threshold}")
            if 0 < total_storage_free < self.storage_free_threshold:
                logger.info(f"system free space {total_storage_free} < threshold {self.storage_free_threshold}")
            if total_storage_free < 0:
                logger.warning(f"total size of torrents exceed storage_total_limit: {-total_storage_free} bytes")
            self.disk_free = min(system_free, total_storage_free)
            logger.debug(f"system_free={system_free}, total_storage_free={total_storage_free}")
        else:
            self.disk_free = shutil.disk_usage(self.storage_path).free
        
        # update storage_auto_free
        if self.storage_auto_limit is not None:
            auto_storage_usage = 0
            for item in self.auto_list:
                auto_storage_usage += item.size
            self.storage_auto_free = self.storage_auto_limit - auto_storage_usage
        else:
            self.storage_auto_free = None

        logger.debug(f"Disk_free space = {self.disk_free}, storage_auto free = {self.storage_auto_free}")
    
    def _judger_fastflow(self,job:Job, active_threshold_sec=60*60)->bool:
        """
        Judge wether to delete a torrent
        """
        # job should be completed
        if job.progress < 1:  # progress = percentage / 100
            logger.debug(f"{job.name} progress:{job.progress:.2f}")
            return False
        # actived torrent should not deleted
        if time.time() - job.last_activity < active_threshold_sec:
            logger.debug(f"{job.name} actived in {time.time() - job.last_activity :.2f} secs")
            return False
        # share ratio satisfy the limit
        if job.ratio > self.min_up_ratio:
            logger.info(f"{job.name} has ratio {job.ratio:.2f} > {self.min_up_ratio}, will delete.")
            return True
        # seeding time satisfy the limit
        if job.seeding_time > self.min_seed_sec:
            logger.info(f"{job.name} has seed time {job.seeding_time:.2f} > {self.min_seed_sec}, will delete.")
            return True
        
        logger.debug(f"{job.name} progress:{job.progress:.2f} ratio:{job.ratio:.2f} seed time:{job.seeding_time/3600.0 :.2f}h")
        return False

    def _judger_nearestone(self, wait_list: list[Torrent], earliest_secs=6*60) -> list[Torrent] :
        # calculate maximum free space for new torrents
        free = -1
        if self.storage_auto_free is None:
            free = self.disk_free - self.storage_free_threshold
        else:
            free = min(self.disk_free, self.storage_auto_free) - self.storage_free_threshold
        wait_list.sort(reverse=True)
        # find the nearest torrent , and file size < free
        for item in wait_list:
            if item.filesize < free:
                if time.time() - item.release_datetime.timestamp() < earliest_secs:
                    logger.info(f"judger find torrent to add, size={item.filesize}, url={item.link}")
                    return [item]
                else:
                    logger.debug(f"feed release time is early than {earliest_secs/60 :.2f} min ago")
            else:
                logger.debug(f"file size {item.filesize} is too large")
        return []

    def _judger_next_delay(self, delay_start_ratio: float=0.15, delay_multi: float=600*60)->int:
        """
        delay next refresh if disk free space ratio is low.
        use linear fuction to calculate delay time in secs.
        """
        delay_time = 0
        sys_delay = 0
        total_torrents_delay = 0
        auto_torrents_delay = 0

        log_str = ""
        if self.storage_path is not None:
            sys_usage = shutil.disk_usage(self.storage_path)
            sys_ratio = 1.0*sys_usage.free / sys_usage.total
            if sys_ratio < delay_start_ratio:
                sys_delay = (delay_start_ratio - sys_ratio) * delay_multi
            log_str += f"sys_ratio={sys_ratio:.3f} "
        
        if self.storage_total_limit is not None:
            if self.disk_free <= 0:
                return delay_start_ratio*delay_multi
            total_ratio = 1.0*self.disk_free/self.storage_total_limit
            if total_ratio < delay_start_ratio:
                total_torrents_delay = (delay_start_ratio - total_ratio) * delay_multi
            log_str += f"total_ratio={total_ratio:.3f} "
        
        if self.storage_auto_limit is not None:
            if self.storage_auto_free <= 0:
                return delay_start_ratio*delay_multi
            auto_ratio = 1.0*self.storage_auto_free/self.storage_auto_limit
            if auto_ratio < delay_start_ratio:
                auto_torrents_delay = (delay_start_ratio - auto_ratio) * delay_multi
            log_str += f"auto_ratio={auto_ratio:.3f} "
        
        delay_time = max([sys_delay, total_torrents_delay, auto_torrents_delay])
        logger.debug(log_str+f"sys_delay={sys_delay:.1f} total_delay={total_torrents_delay:.1f} auto_delay={auto_torrents_delay:.1f}")
        if delay_time>0:
            logger.info(f"delay time:{delay_time:.2f} secs")
        if delay_time<0:
            logger.error(f"delay time:{delay_time} < 0")
            return 0
        return int(delay_time)

    def check_deletion(self, judge:Callable[[Job],bool] = None, judger_preset=1):
        """
        iterate all download jobs to determine whether a Job need delete.
        judge(currently not implemented): a function for user to override the default judge function 
                to determine whether to delete a Job
        judger_preset: pre-defined judge policy, valid parameters are: JUDGER_FAST_FLOW
        """
        logger.info(f"checking deletion, num of auto tagged torrent = {len(self.auto_list)}")
        for job in self.auto_list:
            judgement = False
            if judger_preset==Monitor.JUDGER_DELETE_FAST_FLOW:
                judgement = self._judger_fastflow(job=job)
            else:
                logger.error("no judger selected! Programmer should set one of judge and judger_preset. Program exit")
                exit(1)
            
            if judgement is True:
                if not self.raw_run:
                    self.client.torrents_delete(delete_files=True, torrent_hashes=job.hash)

    def check_addition(self, judger_preset=1, err_wait_sec=300, loading_wait_sec=5):
        """
        1.update rss, retrieve new feed. 2.update disk_free and storage_auto_free.
        3.send new feed to judger, get list of torrents to add. 4.add torrent
        """
        logger.info("start check new torrent")
        torrent_list: list[Torrent] = []
        torrent_list_new: list[Torrent] = []
        self.client.rss.refresh_item(item_path=self.tag_name)
        time.sleep(1)
        while True:
            rss_root = self.client.rss_items(include_feed_data=True)
            rss_auto_dict = rss_root[self.tag_name]
            if rss_auto_dict["isLoading"]:
                logger.info(f"rss is loading, wait {loading_wait_sec} sec and retry.")
                time.sleep(loading_wait_sec)
                continue
            if rss_auto_dict["hasError"]:
                logger.warning("rss auto dict has error, wait 300 sec and retry")
                time.sleep(err_wait_sec)
                continue
            article_list = rss_auto_dict["articles"]
            

            for item in article_list:
                torrent_list.append(Torrent(item))
            
            break
        
        # find new torrent in new torrent list.
        torrent_list.sort(reverse=True)
        for torrent in torrent_list:
            found = False
            for old_torrent in self.rss_list:
                if torrent==old_torrent:
                    found = True
                    logger.debug(f"torrent found in old list, {torrent.filesize}=={old_torrent.filesize}")
                    break

            if not found:
                logger.debug(f"new torrent released at {torrent.release_datetime}")
                torrent_list_new.append(torrent)
        
        self.rss_list = torrent_list

        # update free space
        self.update_free_space()

        download_list = []
        if judger_preset == Monitor.JUDGER_ADD_NEAREST_ONE:
            download_list = self._judger_nearestone(torrent_list_new)
        logger.info(f"new rss feed count={len(torrent_list_new)}, download list len={len(download_list)}")

        for torrent in download_list:
            if not self.raw_run:
                result = self.client.torrents.add(urls=torrent.link, save_path=self.download_path, tags=[self.tag_name])
                logger.info(f"add torrent {result}, link = {torrent.link} ")


    
if __name__ == '__main__':
    m = Monitor(raw_run=False, storage_path="/data", download_path='/downloads/', 
                storage_total_limit=200, storage_auto_limit=200,
                qb_host=os.getenv("PYAUTO_HOST",default="localhost"),
                qb_port=os.getenv("PYAUTO_PORT",default=8080),
                qb_username=os.getenv("PYAUTO_UN",default="admin"),
                qb_pw=os.getenv("PYAUTO_P", default="adminadmin"))

    def clear_session(SignalNumber,Frame):
        logger.info(f"signal {signal.Signals(SignalNumber).name} received, exit!")
        m.client.auth_log_out()
        exit(0)
    
    signal.signal(signal.SIGINT, clear_session)
    signal.signal(signal.SIGTERM, clear_session)

    m.start()

