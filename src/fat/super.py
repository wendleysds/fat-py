"""
 * SPDX-License-Identifier: MIT
 *
 * fat-py - A lightweight, pure Python library and command-line management tool for FAT
 *
 * Copyright (c) 2026 Wendley Santos
 *
 * This file is part of fat-py.
 * See the LICENSE file in the project root for license information.
"""

from fat.impl import FAT, FAT12, FAT16, FAT32
import fat.datatypes as types
import fat.consts as consts
from fat.partition import Disk, GPT
import array, os


class FATFD:
	entry: types.FATDirectoryEntry
	firstCluster: int
	currentCluster: int
	dirCluster: int
	cursor: int

	def __init__(self, entry: types.FATDirectoryEntry, dirCluster: int):
		cluster = entry.get_cluster()
		self.entry = entry
		self.firstCluster = cluster
		self.currentCluster = cluster
		self.cursor = 0
		self.dirCluster = dirCluster

def fat_format_name(filename: str) -> str:
	if not filename or len(filename) == 0:
		return '\0'

	if filename == '.':
		return '.          '
	if filename == '..':
		return '..         '

	dot = filename.rfind('.')
	if dot != -1:
		name_part = filename[:dot]
		ext_part = filename[dot+1:]
	else:
		name_part = filename
		ext_part = ''

	name_part = name_part.replace('.', '').replace(' ', '')
	ext_part = ext_part.replace('.', '').replace(' ', '')

	if len(name_part) > 8:
		name_part = name_part[:6] + '~1'

	if len(ext_part) > 3:
		ext_part = ext_part[:3]

	return name_part.ljust(8).upper() + ext_part.ljust(3).upper()


class FATFS:
	fat: FAT

	def __init__(self, disk: Disk, partition: int | None = None, fsInfoStartCluster: int = 3):
		start_lba = 0

		if isinstance(partition, int):
			part = disk.partitions
			idx = partition - 1

			if idx < len(part.entries):
				if isinstance(part, GPT):
					start_lba = part.entries[idx].start_lba
				else:
					start_lba = part.entries[idx].startLBA

		content = disk.read_lba(start_lba, 512)

		if len(content) < 512 or content[510:512] != b'\x55\xAA':
			raise ValueError("Invalid FAT boot sector signature (0x55AA missing)!")

		bpb = types.FATBootHeader.from_bytes(content[0:36])
		fat32ext = types.FAT32ExtendedHeader.from_bytes(content[36:90])
		fat16ext = types.FAT16ExtendedHeader.from_bytes(content[36:64])
		fat12ext = types.FAT12ExtendedHeader.from_bytes(content[36:64])

		fatSize = bpb.FATSz16 if bpb.FATSz16 != 0 else fat32ext.FATSz32
		totSec = bpb.totSec16 if bpb.totSec16 != 0 else bpb.totSec32

		rootDirSectors = ((bpb.rootEntCnt * 32) + (bpb.bytesPerSec - 1)) // bpb.bytesPerSec
		firstDataSector = bpb.rsvdSecCnt + (bpb.numFATs * fatSize) + rootDirSectors

		dataSectors = totSec - firstDataSector
		countOfClusters = dataSectors // bpb.secPerClus if bpb.secPerClus > 0 else 0

		isFat32 = bpb.FATSz16 == 0 or countOfClusters >= 65525
		isFat16 = not isFat32 and countOfClusters >= 4085
		isFat12 = not isFat32 and countOfClusters < 4085

		fatStartSector = bpb.rsvdSecCnt
		fatBytes = fatSize * bpb.bytesPerSec

		offset = (start_lba + fatStartSector) * bpb.bytesPerSec

		if isFat32:
			table = array.array("I")
			table.frombytes(disk.read_at(offset, fatBytes))

			fsinfo_offset = (start_lba + fat32ext.FSInfo) * bpb.bytesPerSec
			fsInfoContent = disk.read_at(fsinfo_offset, 512)

			if len(fsInfoContent) == 512:
				fsInfo = types.FAT32FSInfo.from_bytes(fsInfoContent)
			else:
				fsInfo = types.FAT32FSInfo.create_default()

			if not fsInfo.is_valid():
				fsInfo = types.FAT32FSInfo.create_default(
					free_count=countOfClusters - 1,
					next_free=3
				)
			else:
				if fsInfo.freeClusterCount == 0xFFFFFFFF:
					fsInfo.freeClusterCount = int(countOfClusters - 1)
				if fsInfo.nextFreeCluster == 0xFFFFFFFF:
					fsInfo.nextFreeCluster = int(fsInfoStartCluster)

			self.fat = FAT32(
				bpb, fat32ext, disk, start_lba, table,
				int(countOfClusters), int(firstDataSector),
				int(bpb.bytesPerSec * bpb.secPerClus),
				fsInfo
			)

		elif isFat16:
			table = array.array("H")
			table.frombytes(disk.read_at(offset, fatBytes))

			self.fat = FAT16(
				bpb, fat16ext, disk, start_lba, table,
				int(countOfClusters), int(firstDataSector),
				int(bpb.bytesPerSec * bpb.secPerClus),
			)

		elif isFat12:
			raw_fat = disk.read_at(offset, fatBytes)
			table = bytearray(raw_fat)

			self.fat = FAT12(
				bpb, fat12ext, disk, start_lba, table,
				int(countOfClusters), int(firstDataSector),
				int(bpb.bytesPerSec * bpb.secPerClus),
			)
		else:
			raise ValueError("Invalid FAT volume configuration!")

	@staticmethod
	def format_file(file: str, start_lba: int, end_lba: int, partition: int = 1):
		mode = 'r+b' if os.path.exists(file) else 'w+b'
		with open(file, mode) as f:
			f.seek(0, os.SEEK_END)
			min_size = (end_lba + 1) * 512
			if f.tell() < min_size:
				f.truncate(min_size)

			disk = Disk(f)

			part_size = end_lba - start_lba
			if part_size < 4085:
				FAT12.mkfs(disk, partition, start_lba, end_lba)
			elif part_size < 65525:
				FAT16.mkfs(disk, partition, start_lba, end_lba)
			else:
				FAT32.mkfs(disk, partition, start_lba, end_lba)

	def cluster_to_lba(self, cluster: int) -> int:
		return self.fat.firstDataSector + ((cluster - 2) * self.fat.header_boot.secPerClus)

	def _root_dir_start_sector(self) -> int:
		return self.fat.header_boot.rsvdSecCnt + (self.fat.header_boot.numFATs * self.fat.header_boot.FATSz16)

	def _is_root_dir_cluster(self, dirCluster: int) -> bool:
		if isinstance(self.fat.header_extended, types.FAT32ExtendedHeader):
			return False
		return dirCluster in (consts.ROOT_DIRECTORY, 0xFFFF, -1)

	def _get_directory_sectors(self, dirCluster: int):
		if self._is_root_dir_cluster(dirCluster):
			root_start = self._root_dir_start_sector()
			total_sectors = (self.fat.header_boot.rootEntCnt * 32) // self.fat.header_boot.bytesPerSec
			entries_per_sec = self.fat.header_boot.bytesPerSec // 32

			for sector in range(root_start, root_start + total_sectors):
				yield (sector, entries_per_sec)
		else:
			cluster = dirCluster
			sec_per_clus = self.fat.header_boot.secPerClus
			entries_per_sec = self.fat.header_boot.bytesPerSec // 32

			while True:
				lba = self.cluster_to_lba(cluster)
				for s_off in range(sec_per_clus):
					yield (lba + s_off, entries_per_sec)

				cluster = self.fat.next_cluster(cluster)
				if self.fat.is_eof(cluster):
					break

	def _iter_dir_entries(self, dirCluster: int):
		for sector, entries_count in self._get_directory_sectors(dirCluster):
			sec_byte_offset = self.fat.lba_to_offset(sector)

			for entry_idx in range(entries_count):
				data = self.fat.disk.read_at(sec_byte_offset + (entry_idx * 32), 32)
				if len(data) < 32:
					return

				entry = types.FATDirectoryEntry.from_bytes(data)

				if entry.is_empty():
					return

				if not entry.is_deleted() and not entry.is_lfn():
					yield entry

	def ls(self, dirCluster: int) -> list[types.FATDirectoryEntry]:
		return list(self._iter_dir_entries(dirCluster))

	def search(self, dirCluster: int, name: str, formatName: bool = True) -> types.FATDirectoryEntry | None:
		formatted_name = fat_format_name(name) if formatName else name.ljust(11).upper()

		for entry in self._iter_dir_entries(dirCluster):
			entry_name = entry.name.decode('latin1', errors='ignore')
			if entry_name == formatted_name:
				return entry

		return None

	def create(self, dirCluster: int, name: str, attr: int) -> int:
		formatted_name = fat_format_name(name)

		# Do not allow duplicate entries.
		if self.search(dirCluster, formatted_name, formatName=False) is not None:
			return -2

		is_dir = bool(attr & consts.DIRECTORY)

		# Allocate the first cluster only for directories.
		new_cluster = 0

		if is_dir:
			new_cluster = self._alloc_cluster()
			if new_cluster < 0:
				return -1

		# Find a free directory entry slot.
		slot = self._find_free_directory_slot(dirCluster)

		if slot is None:
			# Directory could not be expanded.
			if new_cluster:
				self.fat.set_clus(new_cluster, consts.UNUSED)

			return -1

		sector, entry_idx = slot

		# Create and write the directory entry.
		entry = self._make_directory_entry(
			formatted_name,
			attr,
			new_cluster,
		)

		self._write_directory_entry(
			sector,
			entry_idx,
			entry,
		)

		# Initialize "." and ".." for directories.
		if is_dir:
			self._init_subdirectory(new_cluster, dirCluster)

		self.fat.update()

		return new_cluster

	def _alloc_cluster(self) -> int:
		cluster = self.fat.free_cluster()

		if cluster < 2 or self.fat.is_eof(cluster):
			return -1

		self.fat.set_clus(cluster, self.fat.get_eof())

		return cluster

	def _find_free_directory_slot(
		self,
		dirCluster: int,
	) -> tuple[int, int] | None:
		# First search for an existing free entry.
		for sector, entries_count in self._get_directory_sectors(dirCluster):
			sector_offset = self.fat.lba_to_offset(sector)

			for entry_idx in range(entries_count):
				data = self.fat.disk.read_at(sector_offset + (entry_idx * 32), 32)

				if len(data) < 32:
					break

				entry = types.FATDirectoryEntry.from_bytes(data)

				if entry.is_free_slot():
					return sector, entry_idx

		# No free slot. Try to expand the directory.
		if self._is_root_dir_cluster(dirCluster):
			return None

		last_cluster = self._directory_last_cluster(dirCluster)
		expanded_cluster = self.fat.append_cluster(last_cluster)

		if expanded_cluster < 0:
			return None

		# A newly allocated directory cluster must be empty.
		self._zero_cluster(expanded_cluster)

		return self.cluster_to_lba(expanded_cluster), 0

	def _directory_last_cluster(self, dirCluster: int) -> int:
		cluster = dirCluster

		while True:
			next_cluster = self.fat.next_cluster(cluster)

			if self.fat.is_eof(next_cluster):
				return cluster

			cluster = next_cluster

	def _zero_cluster(self, cluster: int) -> None:
		lba = self.cluster_to_lba(cluster)
		offset = self.fat.lba_to_offset(lba)
		self.fat.disk.write_at(offset, b'\x00' * self.fat.clusterSize)

	def _make_directory_entry(
		self,
		name: str,
		attr: int,
		cluster: int,
	) -> types.FATDirectoryEntry:
		return types.FATDirectoryEntry(
			name=name.encode('latin1'),
			attr=attr,
			NTRes=0,
			crtTimeTenth=0,
			crtTime=0,
			crtDate=0x5461,
			lstAccDate=0x5461,
			fstClusHI=(cluster >> 16) & 0xFFFF,
			wrtTime=0,
			wrtDate=0x5461,
			fstClusLO=cluster & 0xFFFF,
			fileSize=0,
		)

	def _write_directory_entry(
		self,
		sector: int,
		entry_idx: int,
		entry: types.FATDirectoryEntry,
	) -> None:
		offset = self.fat.lba_to_offset(sector) + (entry_idx * 32)
		self.fat.disk.write_at(offset, entry.to_bytes())

	def _init_subdirectory(
		self,
		cluster: int,
		parent_cluster: int,
	) -> None:
		lba = self.cluster_to_lba(cluster)
		offset = self.fat.lba_to_offset(lba)

		# clear dir
		self.fat.disk.write_at(offset, b'\x00' * self.fat.clusterSize)

		# "."
		dot = self._make_directory_entry(
			'.',
			consts.DIRECTORY,
			cluster,
		)

		# ".."
		parent = (
			parent_cluster
			if not self._is_root_dir_cluster(parent_cluster)
			else 0
		)

		dotdot = self._make_directory_entry(
			'..',
			consts.DIRECTORY,
			parent,
		)

		self.fat.disk.write_at(offset, dot.to_bytes() + dotdot.to_bytes())

	def remove(self, dirCluster: int, name: str) -> int:
		formatted_name = fat_format_name(name)

		for sector, entries_count in self._get_directory_sectors(dirCluster):
			sec_byte_offset = self.fat.lba_to_offset(sector)

			for entry_idx in range(entries_count):
				offset = sec_byte_offset + (entry_idx * 32)
				data = self.fat.disk.read_at(offset, 32)
				if len(data) < 32:
					break

				entry = types.FATDirectoryEntry.from_bytes(data)
				if entry.is_empty():
					return -1

				if entry.is_deleted() or entry.is_lfn():
					continue

				if entry.name.decode('latin1', errors='ignore') == formatted_name:
					# Mark entry deleted
					deleted_name = bytearray(entry.name)
					deleted_name[0] = 0xE5
					entry.name = bytes(deleted_name)

					self.fat.disk.write_at(offset, entry.to_bytes())

					# Free cluster chain
					start_clus = entry.get_cluster()
					if start_clus >= 2:
						self.fat.free_chain(start_clus)

					self.fat.update()
					return 0

		return -1

	def walk(self, path: str) -> types.FATDirectoryEntry | None:
		parts = [p for p in path.strip('/').split('/') if p]

		if isinstance(self.fat.header_extended, types.FAT32ExtendedHeader):
			root_cluster = self.fat.header_extended.rootClus
		else:
			root_cluster = consts.ROOT_DIRECTORY

		if not parts:
			root = types.FATDirectoryEntry(
				name=b'ROOT       ',
				attr=consts.DIRECTORY | consts.SYSTEM,
				NTRes=0, crtTimeTenth=0, crtTime=0, crtDate=0,
				lstAccDate=0, fstClusHI=0, wrtTime=0, wrtDate=0,
				fstClusLO=0, fileSize=0
			)
			if root_cluster != consts.ROOT_DIRECTORY:
				root.set_cluster(root_cluster)
			else:
				root.set_cluster(consts.ROOT_DIRECTORY)
			return root

		curr_cluster = root_cluster
		target_entry = None

		for part in parts:
			target_entry = self.search(curr_cluster, part)
			if not target_entry:
				return None

			if not target_entry.is_directory() and part != parts[-1]:
				return None

			curr_cluster = target_entry.get_cluster()

		return target_entry

	def _update_entry_on_disk(self, dirCluster: int, entry: types.FATDirectoryEntry):
		formatted_name = entry.name.decode('latin1', errors='ignore')

		for sector, entries_count in self._get_directory_sectors(dirCluster):
			sec_byte_offset = self.fat.lba_to_offset(sector)

			for entry_idx in range(entries_count):
				offset = sec_byte_offset + (entry_idx * 32)
				data = self.fat.disk.read_at(offset, 32)
				if len(data) < 32:
					break

				curr_entry = types.FATDirectoryEntry.from_bytes(data)
				if curr_entry.name.decode('latin1', errors='ignore') == formatted_name:
					self.fat.disk.write_at(offset, entry.to_bytes())
					return True

		return False

	def open(self, path: str) -> FATFD | None:
		path = path.rstrip('/')
		tokens = path.split('/')
		filename = tokens[-1]
		parent_path = '/'.join(tokens[:-1]) if len(tokens) > 1 else '/'
		if not parent_path:
			parent_path = '/'

		parent_entry = self.walk(parent_path)
		if not parent_entry:
			return None

		dir_cluster = parent_entry.get_cluster()
		if parent_path == '/' and not isinstance(self.fat.header_extended, types.FAT32ExtendedHeader):
			dir_cluster = consts.ROOT_DIRECTORY

		file_entry = self.search(dir_cluster, filename)
		if not file_entry:
			return None

		return FATFD(file_entry, dir_cluster)

	def seek(self, fd: FATFD, offset: int, whence: int = 0) -> int:
		filesize = fd.entry.fileSize
		if whence == 0:
			target = offset
		elif whence == 1:
			target = fd.cursor + offset
		elif whence == 2:
			target = filesize + offset
		else:
			return -1

		if target < 0 or target > filesize:
			return -1

		clusterOffset = target // self.fat.clusterSize
		cluster = fd.firstCluster

		for _ in range(clusterOffset):
			cluster = self.fat.next_cluster(cluster)
			if self.fat.is_eof(cluster):
				return -1

		fd.currentCluster = cluster
		fd.cursor = target
		return target

	def read(self, fd: FATFD, count: int) -> bytes:
		if fd.cursor >= fd.entry.fileSize or count <= 0:
			return b''

		remaining = min(count, fd.entry.fileSize - fd.cursor)
		content = bytearray()

		while remaining > 0 and fd.currentCluster >= 2 and not self.fat.is_eof(fd.currentCluster):
			clusterOffset = fd.cursor % self.fat.clusterSize
			bytesLeftInCluster = self.fat.clusterSize - clusterOffset

			toRead = min(remaining, bytesLeftInCluster)
			lba = self.cluster_to_lba(fd.currentCluster)
			byte_offset = self.fat.lba_to_offset(lba) + clusterOffset

			data = self.fat.disk.read_at(byte_offset, toRead)
			read_len = len(data)

			if read_len == 0:
				break

			content.extend(data)
			fd.cursor += read_len
			remaining -= read_len

			if fd.cursor % self.fat.clusterSize == 0 and remaining > 0:
				next_clus = self.fat.next_cluster(fd.currentCluster)
				if self.fat.is_eof(next_clus):
					break
				fd.currentCluster = next_clus

		return bytes(content)

	def write(self, fd: FATFD, buffer: str | bytes, count: int) -> int:
		if isinstance(buffer, str):
			buffer = buffer.encode('latin1')

		buffer = buffer[:count]
		remaining = len(buffer)
		totalWritten = 0

		# Allocate initial cluster if file is empty
		if fd.firstCluster < 2:
			new_cluster = self.fat.free_cluster()
			if new_cluster == -1 or self.fat.is_eof(new_cluster):
				return -1

			self.fat.set_clus(new_cluster, self.fat.get_eof())
			fd.firstCluster = new_cluster
			fd.currentCluster = new_cluster
			fd.entry.set_cluster(new_cluster)

		while remaining > 0:
			clusterOffset = fd.cursor % self.fat.clusterSize
			bytesLeftInCluster = self.fat.clusterSize - clusterOffset
			toWrite = min(remaining, bytesLeftInCluster)

			lba = self.cluster_to_lba(fd.currentCluster)
			byte_offset = self.fat.lba_to_offset(lba) + clusterOffset

			written = self.fat.disk.write_at(byte_offset, buffer[totalWritten:totalWritten + toWrite])

			fd.cursor += written
			totalWritten += written
			remaining -= written

			if fd.cursor % self.fat.clusterSize == 0 and remaining > 0:
				nextCluster = self.fat.next_cluster(fd.currentCluster)
				if self.fat.is_eof(nextCluster):
					nextCluster = self.fat.append_cluster(fd.currentCluster)
					if nextCluster < 0:
						break

				fd.currentCluster = nextCluster

		if fd.cursor > fd.entry.fileSize:
			fd.entry.fileSize = fd.cursor

		# Write updated directory entry back to disk
		self._update_entry_on_disk(fd.dirCluster, fd.entry)
		self.fat.update()

		return totalWritten
