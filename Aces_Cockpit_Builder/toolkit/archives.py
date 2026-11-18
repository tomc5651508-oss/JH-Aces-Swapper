import gtp_extract as gx
class Archives:
    """FAT index of every data\\*.gtp: lower-case path -> (gtp, off, size); plus all directories."""

    def __init__(self, data_dir):
        self.files, self.dirs, self.dups = {}, set(), []
        for gtp in sorted(data_dir.glob("*.gtp")):
            try:
                with open(gtp, "rb") as f:
                    dirs, files = gx.read_fat(f)
            except Exception as e:  # noqa: BLE001
                print(f"  warn: cannot index {gtp.name}: {e}")
                continue
            for _rid, _h, name in dirs:
                self.dirs.add(name.lower().strip("/"))
            for off, size, _h, name in files:
                key = name.lower().lstrip("/")
                if key in self.files:
                    self.dups.append((key, self.files[key][0].name, gtp.name))
                self.files[key] = (gtp, off, size)
                parts = key.split("/")
                for i in range(1, len(parts)):
                    self.dirs.add("/".join(parts[:i]))

    def listing(self, prefix):
        prefix = prefix.lower().strip("/") + "/"
        return {k: v for k, v in self.files.items() if k.startswith(prefix)}

    def read(self, key):
        gtp, off, size = self.files[key]
        with open(gtp, "rb") as f:
            data, _note = gx.file_data(f, off, size)
        return data[:size]

    def exists(self, key):
        key = key.lower().strip("/")
        return key in self.files or key in self.dirs


