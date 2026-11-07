"""一个 daemon 线程轮询所有文档；关闭时注销，不读取或覆盖正文。"""
import os
import threading


class Watcher:
    def __init__(self):
        self.entries = {}
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.thread = None

    @staticmethod
    def stamp(path):
        try:
            stat = os.stat(path)
            return stat.st_mtime_ns, stat.st_size
        except OSError:
            return None

    def watch(self, key, path, callback):
        with self.lock:
            self.entries[key] = (path, self.stamp(path), callback)
            if self.thread is None:
                self.thread = threading.Thread(target=self.run, daemon=True, name='document-watcher')
                self.thread.start()

    def remove(self, key):
        with self.lock:
            self.entries.pop(key, None)

    def poll(self):
        with self.lock:
            entries = list(self.entries.items())
        for key, entry in entries:
            path, previous, callback = entry
            current = self.stamp(path)
            if current == previous:
                continue
            with self.lock:
                if self.entries.get(key) is not entry:
                    continue
                self.entries[key] = (path, current, callback)
            try:
                callback(path, current)
            except Exception:
                # 单文档回调失败不能停止其他文档的监听。
                pass

    def run(self):
        while not self.stop.wait(1):
            self.poll()


watcher = Watcher()
