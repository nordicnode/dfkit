-- agent/undesignate - clear dig/chop designations in a box
-- usage: agent/undesignate <x0> <y0> <z0> <x1> <y1> <z1>
local json = require('json')
local a = { ... }
local x0, y0, z0 = tonumber(a[1]), tonumber(a[2]), tonumber(a[3])
local x1, y1, z1 = tonumber(a[4]), tonumber(a[5]), tonumber(a[6])

if not x0 or not x1 then
    print('usage: agent/undesignate <x0> <y0> <z0> <x1> <y1> <z1>')
    return
end

local cleared = 0
for z = math.min(z0, z1), math.max(z0, z1) do
    for x = math.min(x0, x1), math.max(x0, x1) do
        for y = math.min(y0, y1), math.max(y0, y1) do
            local b = dfhack.maps.getTileBlock(x, y, z)
            if b then
                local d = b.designation[x % 16][y % 16]
                if d.dig ~= 0 then
                    d.dig = 0 -- tile_dig_designation.No
                    cleared = cleared + 1
                end
            end
        end
    end
end

print(json.encode({ cleared = cleared }))
