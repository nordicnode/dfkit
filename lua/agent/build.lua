-- agent/build - create a building at a tile without the UI.
-- usage: agent/build <name> <x> <y> <z>
local json = require('json')
local buildings = require('dfhack.buildings')
local args = { ... }
local name = (args[1] or ''):lower()
local x, y, z = tonumber(args[2]), tonumber(args[3]), tonumber(args[4])

if not name or not x or not y or not z then
    print('usage: agent/build <name> <x> <y> <z>')
    return
end

local WORKSHOPS = {
    carpenter = 'Carpenters', mason = 'Masons', farmer = 'Farmers',
    jeweler = 'Jewelers', craftsdwarf = 'Craftsdwarfs', clothier = 'Clothiers',
    leatherworks = 'Leatherworks', still = 'Still', kitchen = 'Kitchen',
    butcher = 'Butchers', tanner = 'Tanners', loom = 'Loom', ashery = 'Ashery',
    dyer = 'Dyers', millstone = 'Millstone', quern = 'Quern',
    kennels = 'Kennels', mechanic = 'Mechanics', bowyer = 'Bowyers',
    siege = 'Siege', tool = 'Tool',
}
local FURNACES = {
    smelter = 'Smelter', kiln = 'Kiln', glass_furnace = 'GlassFurnace',
    wood_furnace = 'WoodFurnace', magma_smelter = 'MagmaSmelter',
    magma_kiln = 'MagmaKiln', magma_glass_furnace = 'MagmaGlassFurnace',
}
local SIMPLE = {
    bed = 'Bed', table = 'Table', chair = 'Chair', door = 'Door',
    cabinet = 'Cabinet', coffin = 'Coffin', statue = 'Statue', well = 'Well',
    armor_stand = 'ArmorStand', weapon_rack = 'WeaponRack', box = 'Box',
}

local spec
if WORKSHOPS[name] and df.workshop_type[WORKSHOPS[name]] then
    spec = { type = df.building_type.Workshop, subtype = df.workshop_type[WORKSHOPS[name]] }
elseif FURNACES[name] and df.furnace_type[FURNACES[name]] then
    spec = { type = df.building_type.Furnace, subtype = df.furnace_type[FURNACES[name]] }
elseif SIMPLE[name] and df.building_type[SIMPLE[name]] then
    spec = { type = df.building_type[SIMPLE[name]] }
else
    print('unknown building: ' .. name)
    return
end

spec.pos = { x = x, y = y, z = z }
local building, err = buildings.constructBuilding(spec)
if not building then
    print('cannot build ' .. name .. ': ' .. tostring(err))
    return
end

print(json.encode({
    built = name,
    id = building.id,
    type = tostring(building:getType()),
    pos = { x, y, z },
}))
