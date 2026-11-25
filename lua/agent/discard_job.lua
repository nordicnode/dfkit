-- agent/discard_job <job_id> - remove a stale job and release its items.
-- Follows the ordering in gui/advfort: refs -> building vector -> list -> delete.
local json = require('json')
local id = tonumber(({ ... })[1])
local utils = require('utils')

local job
for _, j in utils.listpairs(df.global.world.jobs.list) do
    if j.id == id then job = j end
end
if not job then
    print(json.encode({ ok = false, error = 'no such job' }))
    return
end

local released = 0
for _, ref in ipairs(job.general_refs) do
    local t = ref:getType()
    if t == df.general_ref_type.ITEM then
        local it = ref:getItem()
        if it then
            it.flags.in_job = false
            released = released + 1
        end
    elseif t == df.general_ref_type.BUILDING_HOLDER then
        local b = ref:getBuilding()
        if b and b.jobs then
            for i, v in ipairs(b.jobs) do
                if v == job then b.jobs:erase(i) break end
            end
        end
    elseif t == df.general_ref_type.UNIT_WORKER then
        local u = ref:getUnit()
        if u and u.job.current_job == job then u.job.current_job = nil end
    end
end

local link = job.list_link
if link.prev then link.prev.next = link.next end
if link.next then link.next.prev = link.prev end
link:delete()
job:delete()
print(json.encode({ ok = true, id = id, released_items = released }))
