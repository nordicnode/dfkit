-- agent/count_dig <x0> <y0> <z0> <x1> <y1> <z1> - count tiles with a dig designation
local json = require('json')
local a = { ... }
local x0, y0, z0 = tonumber(a[1]), tonumber(a[2]), tonumber(a[3])
local x1, y1, z1 = tonumber(a[4]), tonumber(a[5]), tonumber(a[6])
local n = 0
for z = math.min(z0, z1), math.max(z0, z1) do
    for x = math.min(x0, x1), math.max(x0, x1) do
        for y = math.min(y0, y1), math.max(y0, y1) do
            local b = dfhack.maps.getTileBlock(x, y, z)
            if b and b.designation[x % 16][y % 16].dig ~= 0 then n = n + 1 end
        end
    end
end
print(json.encode({ designated = n }))
