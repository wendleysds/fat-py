# fat-py

A lightweight, pure Python library and command-line management tool for **FAT12**, **FAT16**, and **FAT32** file systems with full support for **MBR** and **GPT** partition tables.

---

## Features

- **Multi-Format Support:** Format, read, write, and inspect **FAT12**, **FAT16**, and **FAT32** volumes.
- **Partition Scheme Aware:** Support for parsing and updating **MBR** (Master Boot Record) and **GPT** (GUID Partition Table) partitioning schemes, including automated GPT CRC32 checksum updating.
- **File System Operations:**
  - `format`: Format partition regions with appropriate FAT variant based on size.
  - `info`: Print volume boot record (BPB, extended header, FSInfo).
  - `ls`: List directory contents with cluster indices and file sizes.
  - `cat`: Read and stream file content directly to `stdout`.
  - `put`: Upload local files from host system into FAT volumes.
  - `mkdir`: Create nested subdirectories with automatically initialized `.` and `..` entries.
  - `rm`: Remove files and free allocated cluster chains in FAT tables.
  - `stat`: Inspect directory entry metadata and trace cluster/LBA chains.
- **Clean Architecture:** Abstract `Disk` E/S interface delegating block and sector reads/writes.

---

## Installation

To install in editable mode or as a package:

```bash
pip install -e .
```

---

## Command-Line Interface (CLI) Usage

```bash
# Format a disk partition region
fat-py format disk.img --start-lba 2048 --end-lba 65536 --partition 1

# Inspect volume information
fat-py info disk.img -p 1

# Create a directory
fat-py mkdir disk.img /docs -p 1

# Copy host file into FAT image
fat-py put disk.img README.md /docs/README.TXT -p 1

# List directory contents
fat-py ls disk.img /docs -p 1

# Display file contents
fat-py cat disk.img /docs/README.TXT -p 1

# Remove file
fat-py rm disk.img /docs/README.TXT -p 1

# Inspect file stat and cluster chain
fat-py stat disk.img /docs -p 1
```

---

## Python API Usage

```python
from fat.partition import Disk
from fat.super import FATFS

with open("disk.img", "rb+") as f:
    disk = Disk(f)
    fatfs = FATFS(disk, partition=1)
    
    # List root directory
    entries = fatfs.ls(dirCluster=fatfs.fat.header_extended.rootClus)
    for entry in entries:
        print(entry)
```

---

## Running Tests

To run the automated test suite using `pytest`:

```bash
pytest -v
```

## License

[MIT License](LICENSE)