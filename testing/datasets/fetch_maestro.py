"""Pull individual MAESTRO v3 recordings (WAV + aligned MIDI) without downloading the 101 GB zip.

    .venv/bin/python testing/datasets/fetch_maestro.py --shortest 6
    .venv/bin/python testing/datasets/fetch_maestro.py --name "2008/MIDI-Unprocessed_09_R3_2008_01-07_ORIG_MID--AUDIO_09_R3_2008_wav--2"

The zip's index sits at its end, so HTTP range requests read the index and then only the members
asked for. Files land in ~/Desktop/calhacks/datasets/maestro/. MAESTRO is CC BY-NC-SA 4.0:
real Yamaha Disklavier concert recordings with MIDI aligned to about 3 ms.
"""

import argparse
import csv
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

URL = 'https://huggingface.co/datasets/projectlosangeles/maestro-v3.0.0/resolve/main/maestro-v3.0.0.zip'
CSV = 'https://storage.googleapis.com/magentadata/datasets/maestro/v3.0.0/maestro-v3.0.0.csv'
OUT = Path.home() / 'Desktop' / 'calhacks' / 'datasets' / 'maestro'


class RemoteFile(io.RawIOBase):
    """A seekable, read-only file over HTTP range requests, cached in 1 MB blocks."""

    def __init__(self, url, block=1 << 20):
        self.url, self.block, self.pos, self.cache = url, block, 0, {}
        request = urllib.request.Request(url, method='HEAD')
        with urllib.request.urlopen(request, timeout=60) as response:
            self.size = int(response.headers['Content-Length'])

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = offset if whence == 0 else self.pos + offset if whence == 1 else self.size + offset
        return self.pos

    def _block(self, index):
        if index not in self.cache:
            start = index * self.block
            end = min(self.size, start + self.block) - 1
            request = urllib.request.Request(self.url, headers={'Range': f'bytes={start}-{end}'})
            for attempt in range(6):
                try:
                    with urllib.request.urlopen(request, timeout=120) as response:
                        self.cache[index] = response.read()
                    break
                except OSError:
                    if attempt == 5:
                        raise
            if len(self.cache) > 64:
                self.cache.pop(next(iter(self.cache)))
        return self.cache[index]

    def read(self, size=-1):
        if size < 0:
            size = self.size - self.pos
        out = bytearray()
        while size > 0 and self.pos < self.size:
            index, offset = divmod(self.pos, self.block)
            chunk = self._block(index)[offset:offset + size]
            out += chunk
            self.pos += len(chunk)
            size -= len(chunk)
        return bytes(out)

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--shortest', type=int, default=0, help='fetch the N shortest recordings')
    parser.add_argument('--name', action='append', default=[], help='audio filename without .wav (repeatable)')
    args = parser.parse_args(argv[1:])
    OUT.mkdir(parents=True, exist_ok=True)
    meta = OUT / 'maestro-v3.0.0.csv'
    if not meta.exists():
        urllib.request.urlretrieve(CSV, meta)
    rows = list(csv.DictReader(meta.open()))
    wanted = [r for r in rows if Path(r['audio_filename']).with_suffix('').as_posix() in args.name]
    if args.shortest:
        wanted += sorted(rows, key=lambda r: float(r['duration']))[:args.shortest]
    if not wanted:
        parser.error('Nothing to fetch. Use --shortest N or --name.')
    archive = zipfile.ZipFile(RemoteFile(URL))
    members = {Path(n).as_posix(): n for n in archive.namelist()}
    for row in wanted:
        for key in ('audio_filename', 'midi_filename'):
            name = row[key]
            target = OUT / name
            if target.exists():
                continue
            member = next((members[m] for m in members if m.endswith(name)), None)
            if member is None:
                print(f'not in the archive: {name}')
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, open(target, 'wb') as sink:
                while chunk := source.read(1 << 20):
                    sink.write(chunk)
            print(f'{target.relative_to(OUT)}  {target.stat().st_size / 1e6:.1f} MB', flush=True)
        print(f"  = {row['canonical_composer']}, {row['canonical_title']} ({float(row['duration']):.0f} s, {row['split']})", flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
