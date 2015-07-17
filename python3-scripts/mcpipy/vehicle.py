#
# Code under the MIT license by Alexander Pruss
#

"""
 Make a moving vehicle out of whatever blocks the player is standing near.

 python [options [name]]
 options can include:
   b: want an airtight bubble in the vehicle for going underwater
   n: non-destructive mode
   q: don't want the vehicle to flash as it is scanned
   l: load vehicle from vehicles/name.py
   s: save vehicle to vehicles/name.py and quit

 The vehicle detection algorithm works as follows:
   first, search for nearest non-terrain block within distance SCAN_DISTANCE of the player
   second, get the largest connected set of non-terrain blocks, including diagonal connections, up to
     distance MAX_DISTANCE in each coordinate
   in bubble mode, add the largest set of air blocks, excluding diagonal connections, or a small bubble about the
     player if the the vehicle is not airtight
"""

from .mcpi.minecraft import *
from .mcpi.block import *
from math import *
from sys import maxsize
from copy import copy
import re

class Vehicle():
    # the following blocks do not count as part of the vehicle
    TERRAIN = set((AIR.id,WATER_FLOWING.id,WATER_STATIONARY.id,GRASS.id,DIRT.id,LAVA_FLOWING.id,
                    LAVA_STATIONARY.id,GRASS.id,DOUBLE_TALLGRASS.id,GRASS_TALL.id,BEDROCK.id,GRAVEL.id,SAND.id))

    # ideally, the following blocks are drawn last and erased first
    NEED_SUPPORT = set((SAPLING.id,WATER_FLOWING.id,LAVA_FLOWING.id,GRASS_TALL.id,34,FLOWER_YELLOW.id,
                        FLOWER_CYAN.id,MUSHROOM_BROWN.id,MUSHROOM_RED.id,TORCH.id,63,DOOR_WOOD.id,LADDER.id,
                        66,68,69,70,DOOR_IRON.id,72,75,76,77,SUGAR_CANE.id,93,94,96,104,105,106,108,111,
                        113,115,116,117,122,127,131,132,141,142,143,145,147,148,149,150,151,154,157,
                        167,CARPET.id,SUNFLOWER.id,176,177,178,183,184,185,186,187,188,189,190,191,192,
                        193,194,195,196,197))
    SCAN_DISTANCE = 5
    MAX_DISTANCE = 30
    stairDirectionsClockwise = [2, 1, 3, 0]
    stairToClockwise = [3, 1, 0, 2]
    chestToClockwise = [0,0,0,2,3,1,0,0]
    chestDirectionsClockwise = [2,5,3,4]
    STAIRS = set((STAIRS_COBBLESTONE.id, STAIRS_WOOD.id, 108, 109, 114, 128, 134, 135, 136, 156, 163, 164, 180))
    DOORS = set((DOOR_WOOD.id,193,194,195,196,197,DOOR_IRON.id))
    LADDERS_FURNACES_CHESTS_SIGNS = set((LADDER.id, FURNACE_ACTIVE.id, FURNACE_INACTIVE.id, CHEST.id, 130, 146, 68))
    REDSTONE_COMPARATORS_REPEATERS = set((93,94,149,150,356,404))
    EMPTY = {}

    def __init__(self,mc,nondestructive=False):
        self.mc = mc
        self.nondestructive = nondestructive
        self.highWater = -maxsize-1
        self.baseVehicle = {}
        if hasattr(Minecraft, 'getBlockWithNBT'):
            self.getBlockWithData = self.mc.getBlockWithNBT
            self.setBlockWithData = self.mc.setBlockWithNBT
        else:
            self.getBlockWithData = self.mc.getBlockWithData
            self.setBlockWithData = self.mc.setBlock
        self.curVehicle = {}
        self.curRotation = 0
        self.curLocation = None
        self.saved = {}
        self.baseAngle = 0

    @staticmethod
    def keyFunction(dict,erase,pos):
        ns = pos in dict and dict[pos].id in Vehicle.NEED_SUPPORT
        if ns:
            return (True, pos not in erase or erase[pos].id not in Vehicle.NEED_SUPPORT,
                pos[0],pos[2],pos[1])
        else:
            return (False, pos not in erase or erase[pos].id not in Vehicle.NEED_SUPPORT,
                pos[1],pos[0],pos[2])

    @staticmethod
    def box(x0,y0,z0,x1,y1,z1):
        for x in range(x0,x1+1):
            for y in range(y0,y1+1):
                for z in range(z0,z1+1):
                    yield (x,y,z)

    def getSeed(self,x0,y0,z0):
        scanned = set()
        for r in range(0,Vehicle.SCAN_DISTANCE+1):
            for x,y,z in Vehicle.box(-r,-r,-r,r,r,r):
                if x*x+y*y+z*z <= r*r and (x,y,z) not in scanned:
                    blockId = self.mc.getBlock(x+x0,y+y0,z+z0)
                    scanned.add((x,y,z))
                    if blockId not in Vehicle.TERRAIN:
                        return (x0+x,y0+y,z0+z)
        return None

    def save(self,filename):
        f = open(filename,"w")
        f.write("baseAngle,highWater,baseVehicle="+repr((self.baseAngle,self.highWater,self.baseVehicle))+"\n")
        f.close()

    @staticmethod
    def safeEval(string):
        if "__" in string:
            raise ValueError
        return eval(string)

    def load(self,filename):
        with open(filename) as f:
            data = ''.join(f.readlines())
            result = re.search("=\\s*(.*)",data)
            if result is None:
                raise ValueError
            self.baseAngle,self.highWater,self.baseVehicle = Vehicle.safeEval(result.group(1))
        self.curLocation = None

    def safeSetBlockWithData(self,pos,block):
        """
        Draw block, making sure buttons are not depressed. This is to fix a glitch where launching 
        the vehicle script from a commandblock resulted in re-pressing of the button.
        """
        if block.id == WOOD_BUTTON.id or block.id == STONE_BUTTON.id:
            block = Block(block.id, block.data & ~0x08)
        self.setBlockWithData(pos,block)

    def scan(self,x0,y0,z0,angle=0,flash=True):
        positions = {}
        self.curLocation = (x0,y0,z0)
        self.curRotation = 0
        self.baseAngle = angle

        seed = self.getSeed(x0,y0,z0)
        if seed is None:
            return {}

        block = self.getBlockWithData(seed)
        self.curVehicle = {seed:block}
        if flash and block.id not in Vehicle.NEED_SUPPORT:
            self.mc.setBlock(seed,GLOWSTONE_BLOCK)
        newlyAdded = set(self.curVehicle.keys())

        searched = set()
        searched.add(seed)

        while len(newlyAdded)>0:
            adding = set()
            self.mc.postToChat("Added "+str(len(newlyAdded))+" blocks")
            for q in newlyAdded:
                for x,y,z in Vehicle.box(-1,-1,-1,1,1,1):
                    pos = (x+q[0],y+q[1],z+q[2])
                    if pos not in searched:
                        if ( abs(pos[0]-x0) <= Vehicle.MAX_DISTANCE and
                            abs(pos[1]-y0) <= Vehicle.MAX_DISTANCE and
                            abs(pos[2]-z0) <= Vehicle.MAX_DISTANCE ):
                            searched.add(pos)
                            block = self.getBlockWithData(pos)
                            if block.id in Vehicle.TERRAIN:
                                if ((block.id == WATER_STATIONARY.id or block.id == WATER_FLOWING.id) and 
                                    self.highWater < pos[1]):
                                    self.highWater = pos[1]
                            else:
                                self.curVehicle[pos] = block
                                adding.add(pos)
                                if flash and block.id not in Vehicle.NEED_SUPPORT:
                                    self.mc.setBlock(pos,GLOWSTONE_BLOCK)
            newlyAdded = adding

        self.baseVehicle = {}
        for pos in self.curVehicle:
            self.baseVehicle[(pos[0]-x0,pos[1]-y0,pos[2]-z0)] = self.curVehicle[pos]

        if flash:
            import time
            for pos in sorted(self.curVehicle, key=lambda a : Vehicle.keyFunction(self.curVehicle,Vehicle.EMPTY,a)):
                self.safeSetBlockWithData(pos,self.curVehicle[pos])

    def angleToRotation(self,angle):
        return int(round((angle-self.baseAngle)/90.)) % 4

    def draw(self,x,y,z,angle=0):
        self.curLocation = (x,y,z)
        self.curRotation = self.angleToRotation(angle)
        self.curVehicle = {}
        self.saved = {}
        vehicle = Vehicle.rotate(self.baseVehicle,self.curRotation)
        for pos in sorted(vehicle, key=lambda a : Vehicle.keyFunction(vehicle,Vehicle.EMPTY,a)):
            drawPos = (pos[0] + x, pos[1] + y, pos[2] + z)
            if self.nondestructive:
                self.saved[drawPos] = self.getBlockWithData(drawPos)
            self.safeSetBlockWithData(drawPos,vehicle[pos])
            self.curVehicle[drawPos] = vehicle[pos]
            
    def blankBehind(self):
        for pos in self.saved:
            self.saved[pos] = self.defaultFiller(pos)

    def erase(self):
        todo = {}
        for pos in self.curVehicle:
            if self.nondestructive and pos in self.saved:
                todo[pos] = self.saved[pos]
            else:
                todo[pos] = self.defaultFiller(pos)
        for pos in sorted(todo, key=lambda x : Vehicle.keyFunction(todo,Vehicle.EMPTY,x)):
            self.safeSetBlockWithData(pos,todo[pos])
        self.saved = {}
        self.curVehicle = {}

    def setVehicle(self,dict,startAngle=None):
        if not startAngle is None:
            self.baseAngle = startAngle
        self.baseVehicle = dict

    def setHighWater(self,y):
        self.highWater = y;

    def addBubble(self):
        positions = set()
        positions.add((0,0,0))

        newlyAdded = set()
        newlyAdded.add((0,0,0))

        while len(newlyAdded) > 0:
            adding = set()
            for q in newlyAdded:
                for x,y,z in [(-1,0,0),(1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]:
                    pos = (x+q[0],y+q[1],z+q[2])
                    if (abs(pos[0]) >= Vehicle.MAX_DISTANCE or 
                        abs(pos[1]) >= Vehicle.MAX_DISTANCE or
                        abs(pos[2]) >= Vehicle.MAX_DISTANCE):
                        self.mc.postToChat("Vehicle is not airtight!")
                        positions = set()
                        for x1 in range(-1,2):
                            for y1 in range(-1,2):
                                for z1 in range(-1,2):
                                    if (x1,y1,z1) not in self.baseVehicle:
                                        self.baseVehicle[(x1,y1,z1)] = AIR
                        if (0,2,0) not in self.baseVehicle:
                            self.baseVehicle[(x,y+2,z)] = AIR
                        return
                    if pos not in positions and pos not in self.baseVehicle:
                        positions.add(pos)
                        adding.add(pos)
            newlyAdded = adding
        if (0,0,0) in self.baseVehicle:
            del positions[(0,0,0)]
        for pos in positions:
            self.baseVehicle[pos] = AIR

    # TODO: rotate blocks other than stairs and buttons
    @staticmethod
    def rotateBlock(block,amount):
        if block.id in Vehicle.STAIRS:
            meta = block.data
            return Block(block.id, (meta & ~0x03) |
                         Vehicle.stairDirectionsClockwise[(Vehicle.stairToClockwise[meta & 0x03] + amount) % 4])
        elif block.id in Vehicle.LADDERS_FURNACES_CHESTS_SIGNS:
            meta = block.data & 0x07
            block = copy(block)
            block.data = Vehicle.chestDirectionsClockwise[(Vehicle.chestToClockwise[meta] + amount) % 4]
            return block
        elif block.id == STONE_BUTTON.id or block.id == WOOD_BUTTON.id:
            direction = block.data & 0x07
            if direction < 1 or direction > 4:
                return block
            direction = 1 + Vehicle.stairDirectionsClockwise[(Vehicle.stairToClockwise[direction-1] + amount) % 4]
            return Block(block.id, (block.data & ~0x07) | direction)
        elif block.id in Vehicle.REDSTONE_COMPARATORS_REPEATERS:
            return Block(block.id, (block.data & ~0x03) | (((block.data & 0x03) + amount) & 0x03))
        elif block.id == 96 or block.id == 167:
            # trapdoors
            return Block(block.id, (block.data & ~0x03) | (((block.data & 0x03) - amount) & 0x03))
        elif block.id in Vehicle.DOORS:
            meta = block.data
            if meta & 0x08:
                return block
            else:
                return Block(block.id, (meta & ~0x03) | (((meta & 0x03) + amount) & 0x03))
        else:
            return block

    @staticmethod
    def rotate(dict, amount):
        out = {}
        amount = amount % 4
        if amount == 0:
            return dict
        elif amount == 1:
            for pos in dict:
                out[(-pos[2],pos[1],pos[0])] = Vehicle.rotateBlock(dict[pos],amount)
        elif amount == 2:
            for pos in dict:
                out[(-pos[0],pos[1],-pos[2])] = Vehicle.rotateBlock(dict[pos],amount)
        else:
            for pos in dict:
                out[(pos[2],pos[1],-pos[0])] = Vehicle.rotateBlock(dict[pos],amount)
        return out

    def defaultFiller(self,pos):
         return WATER_STATIONARY if self.highWater is not None and pos[1] <= self.highWater else AIR

    @staticmethod
    def translate(base,x,y,z):
        out = {}
        for pos in base:
            out[(x+pos[0],y+pos[1],z+pos[2])] = base[pos]
        return out

    def moveTo(self,x,y,z,angleDegrees=0):
        rotation = self.angleToRotation(angleDegrees)
        if self.curRotation == rotation and (x,y,z) == self.curLocation:
            return 
        base = Vehicle.rotate(self.baseVehicle, rotation)
        newVehicle = Vehicle.translate(base,x,y,z)
        todo = {}
        erase = {}
        for pos in self.curVehicle:
            if pos not in newVehicle:
                if self.nondestructive and pos in self.saved:
                    todo[pos] = self.saved[pos]
                    del self.saved[pos]
                else:
                    todo[pos] = self.defaultFiller(pos)
            else:
                erase[pos] = self.curVehicle[pos]
        for pos in newVehicle:
            block = newVehicle[pos]
            if pos not in self.curVehicle or self.curVehicle[pos] != block:
                todo[pos] = block
                if pos not in self.curVehicle and self.nondestructive:
                    curBlock = self.getBlockWithData(pos)
                    if curBlock == block:
                        del todo[pos]
                    self.saved[pos] = curBlock
                    erase[pos] = curBlock
        for pos in sorted(todo, key=lambda x : Vehicle.keyFunction(todo,erase,x)):
            self.safeSetBlockWithData(pos,todo[pos])
        self.curVehicle = newVehicle
        self.curLocation = (x,y,z)
        self.curRotation = rotation


if __name__ == '__main__':
    import time
    import sys
    import os

    def save(name):
        dir = os.path.join(os.path.dirname(sys.argv[0]),"vehicles")
        try:
            os.mkdir(dir)
        except:
            pass
        vehicle.save(os.path.join(dir,name+".py"))
        minecraft.postToChat('Vehicle saved as "'+name+'".')

    def load(name):
        dir = os.path.join(os.path.dirname(sys.argv[0]),"vehicles")
        vehicle.load(os.path.join(dir,name+".py"))
        minecraft.postToChat('Vehicle "'+name+'" loaded.')

    def chatHelp():
        minecraft.postToChat("vlist: list vehicles")
        minecraft.postToChat("verase: erase vehicle and exit")
        minecraft.postToChat("vsave filename: save vehicle")
        minecraft.postToChat("vload filename: load vehicle")
        minecraft.postToChat("vdriver [EntityName]: set driver to entity (omit for player) [Jam only]")

    def doScanRectangularPrism(vehicle, basePos, startRot):
        minecraft.postToChat("Indicate extreme points with sword right-click.")
        minecraft.postToChat("Double-click when done.")
        corner1 = [None,None,None]
        corner2 = [None,None,None]
        prevHit = None
        done = False

        minecraft.events.pollBlockHits()

        while not done:
            hits = minecraft.events.pollBlockHits()
            if len(hits) > 0:
                for h in hits:
                    if prevHit != None and h.pos == prevHit.pos:
                        done = True
                        break
                    if corner1[0] == None or h.pos.x < corner1[0]: corner1[0] = h.pos.x
                    if corner1[1] == None or h.pos.y < corner1[1]: corner1[1] = h.pos.y
                    if corner1[2] == None or h.pos.z < corner1[2]: corner1[2] = h.pos.z
                    if corner2[0] == None or h.pos.x > corner2[0]: corner2[0] = h.pos.x
                    if corner2[1] == None or h.pos.y > corner2[1]: corner2[1] = h.pos.y
                    if corner2[2] == None or h.pos.z > corner2[2]: corner2[2] = h.pos.z
                    minecraft.postToChat(""+str(corner2[0]-corner1[0]+1)+"x"+str(corner2[1]-corner1[1]+1)+"x"+str(corner2[2]-corner1[2]+1))
                    prevHit = h
            else:
                prevHit = None
            time.sleep(0.25)

        minecraft.postToChat("Scanning region")
        dict = {}
        for x in range(corner1[0],corner2[0]+1):
            for y in range(corner1[1],corner2[1]+1):
                for z in range(corner1[2],corner2[2]+1):
                    block = vehicle.getBlockWithData(x,y,z)
                    if block.id != AIR.id and block.id != WATER_STATIONARY.id and block.id != WATER_FLOWING.id:
                        pos = (x-basePos.x,y-basePos.y,z-basePos.z)
                        dict[pos] = block
        minecraft.postToChat("Found "+str(len(dict))+" blocks")
        vehicle.setVehicle(dict, startRot)

    bubble = False
    nondestructive = False
    flash = True
    loadName = None
    saveName = None
    scanRectangularPrism = False
    exitAfterDraw = False
    noInitialRotate = False

    if len(sys.argv)>1:
        for x in sys.argv[1]:
            if x == 'b':
                bubble = True
            elif x == 'n':
                nondestructive = True
            elif x == 'q':
                flash = False
            elif x == 's':
                saveName = sys.argv[2]
            elif x == 'l' and len(sys.argv)>2:
                loadName = sys.argv[2]
            elif x == 'L' and len(sys.argv)>2:
                loadName = sys.argv[2]
                exitAfterDraw = True
            elif x == 'r':
                scanRectangularPrism = True

    minecraft = Minecraft()

    getRotation = minecraft.player.getRotation
    getTilePos = minecraft.player.getTilePos

    vehiclePos = getTilePos()
    startRot = getRotation()

    vehicle = Vehicle(minecraft,nondestructive)
    if loadName:
        load(loadName)
    elif scanRectangularPrism:
        doScanRectangularPrism(vehicle,vehiclePos,startRot)
    else:
        minecraft.postToChat("Scanning vehicle")
        vehicle.scan(vehiclePos.x,vehiclePos.y,vehiclePos.z,startRot,flash)
        minecraft.postToChat("Number of blocks: "+str(len(vehicle.baseVehicle)))
        if bubble:
            minecraft.postToChat("Scanning for air bubble")
            vehicle.addBubble()
        if len(vehicle.baseVehicle) == 0:
            minecraft.postToChat("Make a vehicle and then stand on or in it when starting this script.")
            exit()

    if saveName:
        save(saveName)
        exit()
        minecraft.postToChat("Saved: exiting.")

    if exitAfterDraw:
        minecraft.postToChat("Drawing")
        vehicle.draw(vehiclePos.x,vehiclePos.y,vehiclePos.z,startRot)
        minecraft.postToChat("Done")
        exit(0)

    minecraft.postToChat("Now walk around.")

    entity = None
    try:
        minecraft.events.pollChatPosts()
    except:
        pass

    while True:
        pos = getTilePos()
        vehicle.moveTo(pos.x,pos.y,pos.z,getRotation())
        try:
            chats = minecraft.events.pollChatPosts()
            for post in chats:
                args = post.message.split()
                if len(args)>0:
                    if args[0] == 'vhelp':
                        chatHelp()
                    elif args[0] == 'verase':
                        vehicle.erase()
                        exit()
                    elif args[0] == 'vsave':
                        if len(args) > 1:
                            save(args[1])
                        else:
                            chatHelp()
                    elif args[0] == 'vlist':
                        try:
                             out = None
                             dir = os.path.join(os.path.dirname(sys.argv[0]),"vehicles")
                             for f in os.listdir(dir):
                                 if f.endswith(".py"):
                                     if out is not None:
                                         out += ' '+f[:-3]
                                     else:
                                         out = f[:-3]
                             if out is None:
                                 minecraft.postToChat('No saved vehicles')
                             else:
                                 minecraft.postToChat(out)
                        except:
                             minecraft.postToChat('Error listing (maybe no directory?)')
                    elif args[0] == 'vload':
                        if len(args) > 1:
                            try:
                                save("_backup")
                                minecraft.postToChat('Old vehicle saved as "_backup".')
                                load(args[1])
                            except:
                                minecraft.postToChat("Error loading "+args[1])
                        else:
                            chatHelp()
                    elif args[0] == 'vdriver':
                        if entity != None:
                            minecraft.removeEntity(entity)
                            entity = None
                        if len(args) > 1:
                            try:
                                entity = minecraft.spawnEntity(args[1],pos.x,pos.y,pos.z)
                                getRotation = lambda: minecraft.entity.getRotation(entity)
                                getTilePos = lambda: minecraft.entity.getTilePos(entity)
                            except:
                                minecraft.postToChat('Error spawning '+args[1])
                        else:
                            getRotation = minecraft.player.getRotation
                            getTilePos = minecraft.player.getTilePos
        except RequestError:
            pass
        time.sleep(0.25)
