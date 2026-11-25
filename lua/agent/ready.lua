-- agent/ready - preconditions for common production chains
local json = require('json')
local plants, brewable, empty_barrels = 0, 0, 0
for _, it in ipairs(df.global.world.items.all) do
    local t = it:getType()
    if t == df.item_type.PLANT then
        plants = plants + 1
        local mi = dfhack.matinfo.decode(it)
        if mi and mi.material.reaction_product then
            for _, p in ipairs(mi.material.reaction_product.id) do
                if p.value == 'DRINK_MAT' and not it.flags.rotten then
                    brewable = brewable + 1
                end
            end
        end
    elseif t == df.item_type.BARREL then
        if #dfhack.items.getContainedItems(it) == 0 and not it.flags.forbid then
            empty_barrels = empty_barrels + 1
        end
    end
end
print(json.encode({ plants = plants, brewable_plants = brewable,
                    empty_barrels = empty_barrels }))
