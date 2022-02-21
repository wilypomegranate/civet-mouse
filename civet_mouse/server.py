import argparse
import asyncio
import struct
import itertools

import asyncudp
import structlog
import aiofiles

from collections import defaultdict, namedtuple
from dataclasses import dataclass

# from structlog .processors import LogfmtRenderer


# structlog.configure(processors=[LogfmtRenderer()])
log = structlog.get_logger()

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("hid", help="HID Mouse Device to write to.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("-p", "--port", default="5001")
    return parser.parse_args()

async def mouse_interact(hid_fh, button_press: int, x: int, y: int):
    # Write moves to file.
    move = (button_press, x, y)
    log.msg("Writing move.", move=move)
    await hid_fh.write(struct.pack("<bbb", *move))

async def amain():
    args = parse_args()

    log.msg("creating socket", host=args.host, port=args.port)
    sock = await asyncudp.create_socket(local_addr=(args.host, args.port))

    hid = args.hid

    async with aiofiles.open(hid, 'wb+', buffering=0) as hid_fh:
        seqnum_mapping = defaultdict(int)

        while True:
            data, addr = await sock.recvfrom()
            # 0 is initial state so first sn is 1.
            lsn = seqnum_mapping[addr]
            sn, button_press, x, y = struct.unpack('<Hbbb', data)

            if sn - lsn < 1:
                # This is an OOO so just do nothing.
                log.warning("OOO message, skipping.", sn=sn, lsn=lsn)
                sn = lsn
            elif sn - lsn > 1:
                log.warning("Gap detected.", sn=sn, lsn=lsn, size=sn-lsn)
                # Process gap, just log
                await mouse_interact(hid_fh, button_press, x, y)
            elif sn == 65535:
                # Sequence reset, set lsn to 0.
                log.msg("Sequence reset.", sn=sn, lsn=lsn, size=sn-lsn)
                sn = 0
                await mouse_interact(hid_fh, button_press, x, y)
            else:
                # This means the data was in order, process it.
                await mouse_interact(hid_fh, button_press, x, y)
            seqnum_mapping[addr] = sn

        sock.close()

def main():
    asyncio.run(amain())
