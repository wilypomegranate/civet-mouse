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

Screen = namedtuple("Screen", "x y")

@dataclass
class ScreenData:
    """Class for storing screen info."""
    screen: Screen = Screen(0, 0)
    pos: Screen = Screen(0, 0)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("x", type=int)
    parser.add_argument("y", type=int)
    parser.add_argument("hid", help="HID Mouse Device to write to.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("-p", "--port", default="5001")
    return parser.parse_args()

MAX_MOUSE_MOVE_POS = 1
MAX_MOUSE_MOVE_NEG = -1

def calculate_moves(current_pos: int, destination: int):
    # TODO Decide where to limit these values.
    # For now ignore because it really shouldn't affect anything
    # if the mouse is moved "extra".
    to_move = destination - current_pos
    moves = []
    if to_move < 0:
        moves = itertools.chain(*[([MAX_MOUSE_MOVE_NEG] * (to_move // MAX_MOUSE_MOVE_NEG)) , [to_move % MAX_MOUSE_MOVE_NEG ]])
    elif to_move == 0:
        moves =  []
    else:
        moves = itertools.chain(*[([MAX_MOUSE_MOVE_POS] * (to_move // MAX_MOUSE_MOVE_POS)) , [to_move % MAX_MOUSE_MOVE_POS ]])

    return [i for i in moves if i != 0]

async def mouse_interact(screen_data: ScreenData, hid_fh, x: int, y: int, button_press: int):
    # Calculate mouse movement to get to new coordinates.
    # For 0, 0, just force extra movement for now.
    moves = []
    if x > screen_data.screen.x:
        x = screen_data.screen.x
    if y > screen_data.screen.y:
        y = screen_data.screen.y
    if x == 0 and y == 0:
        log.msg("Updating position to top left on init.", current=screen_data.screen, new=(x, y))
        xmoves = calculate_moves(screen_data.screen.x, x)
        ymoves = calculate_moves(screen_data.screen.y, y)
        longest = len(xmoves) if len(xmoves) > len(ymoves) else len(ymoves)
        moves = itertools.zip_longest([button_press] * longest, xmoves, ymoves, fillvalue=0)
    else:
        log.msg("Updating position.", current=screen_data.pos, new=(x, y))
        xmoves = calculate_moves(screen_data.pos.x, x)
        ymoves = calculate_moves(screen_data.pos.y, y)
        longest = len(xmoves) if len(xmoves) > len(ymoves) else len(ymoves)
        moves = itertools.zip_longest([button_press] * longest, xmoves, ymoves, fillvalue=0)

    # Write moves to file.
    for move in moves:
        log.msg("Writing move.", move=move)
        await hid_fh.write(struct.pack("<bbb", *move))

    screen_data.pos = Screen(x, y)

async def amain():
    args = parse_args()

    log.msg("creating socket", host=args.host, port=args.port)
    sock = await asyncudp.create_socket(local_addr=(args.host, args.port))

    screenData = ScreenData(Screen(args.x, args.y))

    hid = args.hid

    async with aiofiles.open(hid, 'wb+', buffering=0) as hid_fh:
        await mouse_interact(screenData, hid_fh, 0, 0, 0)

        seqnum_mapping = defaultdict(int)

        while True:
            data, addr = await sock.recvfrom()
            # 0 is initial state so first sn is 1.
            lsn = seqnum_mapping[addr]
            sn, x, y, button_press = struct.unpack('<HHHb', data)

            if sn - lsn < 1:
                # This is an OOO so just do nothing.
                log.warning("OOO message, skipping.", sn=sn, lsn=lsn)
                sn = lsn
            elif sn - lsn > 1:
                log.warning("Gap detected.", sn=sn, lsn=lsn, size=sn-lsn)
                # Process gap, just log
                await mouse_interact(screenData, hid_fh, x, y, button_press)
            elif sn == 65535:
                # Sequence reset, set lsn to 0.
                log.msg("Sequence reset.", sn=sn, lsn=lsn, size=sn-lsn)
                sn = 0
                await mouse_interact(screenData, hid_fh, x, y, button_press)
            else:
                # This means the data was in order, process it.
                await mouse_interact(screenData, hid_fh, x, y, button_press)
            seqnum_mapping[addr] = sn

        sock.close()

def main():
    asyncio.run(amain())
