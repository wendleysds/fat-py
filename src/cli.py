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

import fat.datatypes as fat_struct
import fat.consts as fat_consts
from fat.super import FATFS, FAT32
from fat.partition import Disk
import argparse, sys, os

def main():
	parser = argparse.ArgumentParser(description="FAT Filesystem Management Tool")
	subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

	# Subcommand: format
	parser_fmt = subparsers.add_parser("format", help="Format volume with FAT12/16/32")
	parser_fmt.add_argument("device", type=str, help="Disk image or device path")
	parser_fmt.add_argument("--start-lba", type=int, default=0, help="Partition start LBA")
	parser_fmt.add_argument("--end-lba", type=int, required=True, help="Partition end LBA")
	parser_fmt.add_argument("--partition", type=int, default=1, help="Partition number (1-4)")

	# Subcommand: ls
	parser_ls = subparsers.add_parser("ls", help="List directory contents")
	parser_ls.add_argument("device", type=str, help="Disk image path")
	parser_ls.add_argument("path", type=str, nargs="?", default="/", help="Directory path")
	parser_ls.add_argument("-p", "--partition", type=int, default=1, help="Partition number (1-4)")

	# Subcommand: cat
	parser_cat = subparsers.add_parser("cat", help="Display file content")
	parser_cat.add_argument("device", type=str, help="Disk image path")
	parser_cat.add_argument("path", type=str, help="File path in volume")
	parser_cat.add_argument("-p", "--partition", type=int, default=1, help="Partition number (1-4)")

	# Subcommand: put
	parser_put = subparsers.add_parser("put", help="Write local file to FAT volume")
	parser_put.add_argument("device", type=str, help="Disk image path")
	parser_put.add_argument("local_file", type=str, help="Local host file path")
	parser_put.add_argument("target_path", type=str, help="Target FAT file path")
	parser_put.add_argument("-p", "--partition", type=int, default=1, help="Partition number (1-4)")

	# Subcommand: mkdir
	parser_mkdir = subparsers.add_parser("mkdir", help="Create directory")
	parser_mkdir.add_argument("device", type=str, help="Disk image path")
	parser_mkdir.add_argument("path", type=str, help="Directory path to create")
	parser_mkdir.add_argument("-p", "--partition", type=int, default=1, help="Partition number (1-4)")

	# Subcommand: rm
	parser_rm = subparsers.add_parser("rm", help="Remove file from FAT volume")
	parser_rm.add_argument("device", type=str, help="Disk image path")
	parser_rm.add_argument("path", type=str, help="File path to delete")
	parser_rm.add_argument("-p", "--partition", type=int, default=1, help="Partition number (1-4)")

	# Subcommand: info
	parser_info = subparsers.add_parser("info", help="Display volume information")
	parser_info.add_argument("device", type=str, help="Disk image path")
	parser_info.add_argument("-p", "--partition", type=int, default=1, help="Partition number (1-4)")

	# Subcommand: stat
	parser_stat = subparsers.add_parser("stat", help="Show file statistics")
	parser_stat.add_argument("device", type=str, help="Disk image path")
	parser_stat.add_argument("path", type=str, help="File path to stat")
	parser_stat.add_argument("-p", "--partition", type=int, default=1, help="Partition number (1-4)")

	args = parser.parse_args()

	if not args.command:
		parser.print_help()
		return 1

	if args.command == "format":
		print(f"Formatting {args.device} (LBA {args.start_lba} to {args.end_lba}, Partition {args.partition})...")
		FATFS.format_file(args.device, args.start_lba, args.end_lba, args.partition)
		print("Format completed successfully.")
		return 0
	
	with open(args.device, 'rb+') as file:
		disk = Disk(file)
		partition = getattr(args, "partition", 1)
		fatfs = FATFS(disk, partition=partition)

		if args.command == "info":
			fat = fatfs.fat
			bpb = fat.header_boot
			ext = fat.header_extended
			print(f"OEM Name:       {bpb.OEMName.decode('latin1', errors='ignore')}")
			print(f"Bytes/Sector:   {bpb.bytesPerSec}")
			print(f"Sectors/Clus:   {bpb.secPerClus}")
			print(f"Cluster Size:   {fat.clusterSize} bytes")
			print(f"Total Clusters: {fat.totalClusters}")
			print(f"FileSystem:     {ext.filSysType.decode('latin1', errors='ignore').strip()}")
			if isinstance(fat, FAT32):
				print(f"FSInfo Free:    {fat.fsInfo.freeClusterCount}")
				print(f"FSInfo NextFree:{fat.fsInfo.nextFreeCluster}")

			return 0

		if args.command == "ls":
			entry = fatfs.walk(args.path)
			if not entry or not entry.is_directory():
				print(f"error: directory '{args.path}' not found")
				return 1

			clus = entry.get_cluster()
			if args.path == '/' and not isinstance(fatfs.fat.header_extended, fat_struct.FAT32ExtendedHeader):
				clus = fat_consts.ROOT_DIRECTORY

			entries = fatfs.ls(clus)
			for e in entries:
				kind = "<DIR> " if e.is_directory() else "      "
				name = e.name.decode('latin1', errors='ignore')
				print(f"{kind} {name}  {e.fileSize} bytes")
			return 0

		if args.command == "cat":
			fd = fatfs.open(args.path)
			if not fd:
				print(f"error: file '{args.path}' not found")
				return 1

			content = fatfs.read(fd, fd.entry.fileSize)
			sys.stdout.buffer.write(content)
			return 0

		if args.command == "put":
			if not os.path.exists(args.local_file):
				print(f"error: local file '{args.local_file}' not found")
				return 1

			with open(args.local_file, "rb") as lf:
				data = lf.read()

			tokens = args.target_path.rstrip('/').split('/')
			filename = tokens[-1]
			parent_path = '/'.join(tokens[:-1]) if len(tokens) > 1 else '/'
			if not parent_path: parent_path = '/'

			parent_entry = fatfs.walk(parent_path)
			if not parent_entry or not parent_entry.is_directory():
				print(f"error: parent directory '{parent_path}' not found")
				return 1

			p_clus = parent_entry.get_cluster()
			if parent_path == '/' and not isinstance(fatfs.fat.header_extended, fat_struct.FAT32ExtendedHeader):
				p_clus = fat_consts.ROOT_DIRECTORY

			fd = fatfs.open(args.target_path)
			if not fd:
				fatfs.create(p_clus, filename, fat_consts.ARCHIVE)
				fd = fatfs.open(args.target_path)

			if not fd:
				print(f"error: failed to create '{args.target_path}'")
				return 1

			written = fatfs.write(fd, data, len(data))
			print(f"Wrote {written} bytes to {args.target_path}")
			return 0

		if args.command == "mkdir":
			tokens = args.path.rstrip('/').split('/')
			dirname = tokens[-1]
			parent_path = '/'.join(tokens[:-1]) if len(tokens) > 1 else '/'
			if not parent_path: parent_path = '/'

			parent_entry = fatfs.walk(parent_path)
			if not parent_entry or not parent_entry.is_directory():
				print(f"error: parent directory '{parent_path}' not found")
				return 1

			p_clus = parent_entry.get_cluster()
			if parent_path == '/' and not isinstance(fatfs.fat.header_extended, fat_struct.FAT32ExtendedHeader):
				p_clus = fat_consts.ROOT_DIRECTORY

			res = fatfs.create(p_clus, dirname, fat_consts.DIRECTORY)
			if res < 0:
				print(f"error: failed to create directory '{args.path}' (code {res})")
				return 1
			print(f"Directory '{args.path}' created successfully.")
			return 0

		if args.command == "rm":
			tokens = args.path.rstrip('/').split('/')
			filename = tokens[-1]
			parent_path = '/'.join(tokens[:-1]) if len(tokens) > 1 else '/'
			if not parent_path: parent_path = '/'

			parent_entry = fatfs.walk(parent_path)
			if not parent_entry or not parent_entry.is_directory():
				print(f"error: parent directory '{parent_path}' not found")
				return 1

			p_clus = parent_entry.get_cluster()
			if parent_path == '/' and not isinstance(fatfs.fat.header_extended, fat_struct.FAT32ExtendedHeader):
				p_clus = fat_consts.ROOT_DIRECTORY

			res = fatfs.remove(p_clus, filename)
			if res < 0:
				print(f"error: failed to remove '{args.path}'")
				return 1
			print(f"Removed '{args.path}'.")
			return 0

		if args.command == "stat":
			entry = fatfs.walk(args.path)
			if not entry:
				print(f"error: file or directory '{args.path}' not found")
				return 1
			print(entry)

			cluster_chain = []
			cur = entry.get_cluster()
			while 0x2 <= cur < fatfs.fat.get_eof():
				cluster_chain.append(cur)
				cur = fatfs.fat.next_cluster(cur)

			lbas = []
			for cluster in cluster_chain:
				lbas.append(fatfs.cluster_to_lba(cluster))

			print("clusters: ", cluster_chain)
			print("lbas: ", [lba + fatfs.fat.start_lba for lba in lbas])
			return 0

if __name__ == "__main__":
	sys.exit(main())