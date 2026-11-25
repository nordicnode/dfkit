-- agent/drink_ids - ids of DRINK items, for before/after verification
local json = require('json')
local ids = {}
for _, it in ipairs(df.global.world.items.all) do
    if it:getType() == df.item_type.DRINK then ids[#ids + 1] = it.id end
end
print(json.encode({ ids = ids }))
