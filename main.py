__author__ = "hite4044 <695663633@qq.com>"

import warnings
import requests
from os import mkdir
from copy import copy
from io import BytesIO
from re import findall
from zipfile import ZipFile
from base64 import b64decode
from Crypto.Cipher import AES
from os.path import join, isdir
from urllib.parse import unquote
from DownloadKit import DownloadKit
from json import loads as json_loads, dump as json_dump

ZIP_HEAD = bytearray([80, 75, 3, 4, 10, 0, 0, 0])
_7Z_HEAD = bytearray([55, 122, 188, 175, 9, 5, 2, 7])
ASSETS_URL = "https://m.ccw.site/user_projects_assets"

warnings.filterwarnings("ignore")


def parse_string(s: str):
    return s + s[-1]


def filter_file_name(file_name: str):
    replaces = list('/\\:*?"<>|')
    for char in replaces:
        file_name = file_name.replace(char, "_")
    return file_name


def format_size(size):
    kb = 1024
    mb = kb * 1024
    gb = mb * 1024
    tb = gb * 1024

    if size >= tb:
        return "%.2f TB" % float(size / tb)
    if size >= gb:
        return "%.2f GB" % float(size / gb)
    if size >= mb:
        return "%.2f MB" % float(size / mb)
    if size >= kb:
        return "%.2f KB" % float(size / kb)


class Project:
    def __init__(self, oid: str):
        self.oid = oid

        self.detail = {}
        self.title = "未获取"
        self.sb3_url = ""
        self._id = ""
        self.update_project_info()

        self.raw_data = bytearray()
        self.zip_data = bytearray()
        self.json = {}
        self.resource_list = []

    def update_project_info(self):
        print("更新作品数据")
        url = "https://community-web.ccw.site/creation/detail"
        post_data = {"oid": self.oid, "accessKey": ""}
        resp_json = requests.post(url, json=post_data).json()
        if resp_json["status"] == 200:
            self.title: str = resp_json["body"]["title"]
            self.sb3_url: str = resp_json["body"]["creationRelease"]["projectLink"]
            self._id: str = self.sb3_url.split("/")[-1].split(".")[0]
            self.detail: str = resp_json["body"]

    def get_sb3_data(self):
        print("下载作品元数据")
        self.raw_data = bytearray(requests.get(self.sb3_url).content)
        print("下载成功, 数据大小:", format_size(len(self.raw_data)))

    def data_text_decrypt(self, text: str) -> str:
        b64_key = "KzdnFCBRvq3" + self._id
        b64_key += "=" * (4 - len(b64_key) % 4)
        key = bytearray(b64decode(b64_key))
        iv = key[:16]  # 取前16个字节为IV
        decrypter = AES.new(key, AES.MODE_CBC, IV=iv)
        return decrypter.decrypt(b64decode(text)).decode("utf-8")

    def get_zip_data(self):
        print("解密出ZIP数据")
        self.zip_data = copy(self.raw_data)

        data_head = self.raw_data[:8]  # 获取文件头
        if data_head == _7Z_HEAD:  # 换头手术, 将7Z头换为ZIP头
            print("换过头的压缩包")
            self.zip_data = ZIP_HEAD + self.raw_data[8:]  # 换头
        elif data_head != ZIP_HEAD:  # 如果开头也不是ZIP头, 那么文件被加密, 进行解密
            print("加密过的压缩包")
            zip_text = self.data_text_decrypt(self.raw_data.decode("utf-8"))  # 解密出数据文本
            data_list = zip_text.split(",")
            if len(data_list[-1]) != "0":
                data_list[-1] = "0"
            self.zip_data = bytearray(map(int, data_list))  # 加载数据
        else:
            print("未加密的压缩包")

    def get_project_json(self):
        print("从压缩包中解密出作品json")
        _zip = ZipFile(BytesIO(self.zip_data))  # 创建压缩包文件
        json_text = _zip.read("project.json").decode("utf-8")
        if not json_text.startswith("{"):  # 文件被加密
            json_text = parse_string(json_text)
            json_text += (4 - len(json_text) % 4) * "="
            json_text = unquote(b64decode(json_text))  # 再b64解码并替换URL文字
            if json_text.startswith("%7�"):  # 艹，BUG！！！
                json_text = "{" + json_text[3:]  # 艹，BUG！！！
            json_text = json_text[:json_text.rindex("}")] + "}"  # 艹，BUG！！！
        self.json = json_loads(json_text)  # 加载为json

    def get_asset_urls(self):
        print("过滤出资源名")
        self.resource_list = findall(r"[0-9a-z]{32}\.\w{2,4}", str(self.json))  # 筛选资源名
        print("共找到资源 %d 个" % len(self.resource_list))

    def download_assets(self, root_path: str):
        self.get_asset_urls()  # 获取资源
        print("开始下载项目资源文件")
        kit = DownloadKit(goal_path=root_path, roads=15, file_exists="skip")  # 创建下载对象
        kit.set.interval(0.5)  # 重试间隔设置0.5秒
        for basename in self.resource_list:
            url = f"{ASSETS_URL}/{basename}"  # 拼接资源地址
            kit.add(url)  # 添加下载任务
        kit.wait(show=True)  # 显示下载进度

    def save_project_json(self, root_path: str):
        print("保存 project.json")
        with open(join(root_path, "project.json"), "w+", encoding="utf-8") as f:
            json_dump(self.json, f, ensure_ascii=False, indent=4)

    def save_project_detail(self, root_path: str):
        print("保存 detail.json")
        with open(join(root_path, "detail.json"), "w+", encoding="utf-8") as f:
            json_dump(self.detail, f, ensure_ascii=False, indent=4)

    def write_zip(self, root_path: str, files_path: str):
        print("开始写入压缩包", flush=True)
        sb3_name = filter_file_name(self.title)
        try:
            with ZipFile(join(root_path, sb3_name + ".sb3"), "w", compresslevel=5) as _zip:
                file_list = self.resource_list.copy()
                file_list.append("project.json")
                file_list.append("detail.json")
                print("文件数量:", len(file_list))
                for basename in file_list:
                    print("\r写入文件:", basename, end=" " * 32)
                    fp = join(files_path, basename)
                    with open(fp, "rb") as file:
                        _zip.writestr(basename, file.read())
                print()
            print("项目sb3已保存至:", join(root_path, sb3_name + ".sb3"))
        except PermissionError:
            print("项目sb3保存失败, 请检查文件是否被占用")

    def download_project(self, root_path: str):
        self.get_sb3_data()
        self.get_zip_data()
        self.get_project_json()

        dir_name = filter_file_name(self.title)
        files_path = join(root_path, dir_name)
        if not isdir(files_path):
            mkdir(files_path)
        self.download_assets(files_path)
        self.save_project_json(files_path)
        self.save_project_detail(files_path)
        self.write_zip(root_path, files_path)


if __name__ == "__main__":
    ids = ["65b39a770cefe35e8b508cdb",
           "62de899f0ad463126c1fe882",
           "61fe6f745419ec36de158069",
           "63c583dc5cdf7229e2ee9afb",
           "65afad64ce20f41a7c1079c7",
           "64da1bf990f36e6d9f719a19",
           "64cf950b52755d1eaa24db67"]
    for _id in ids:
        project = Project(_id)
        project.download_project(r"D:\ccw_project_download_test")
