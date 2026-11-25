-- agent/queue_job - queue a job at a building without touching the UI.
-- usage: agent/queue_job <building_id> <job_type> [reaction_name]
local json = require('json')
local a = { ... }
local bid = tonumber(a[1])
local job_name = a[2]
local reaction = a[3]

if not bid or not job_name then
    print('usage: agent/queue_job <building_id> <job_type> [reaction]')
    return
end

local building
for _, b in ipairs(df.global.world.buildings.all) do
    if b.id == bid then building = b end
end
if not building then
    print('no building with id ' .. bid)
    return
end

local job_type = df.job_type[job_name]
if job_type == nil then
    print('unknown job type: ' .. job_name)
    return
end

local job = df.job:new()
job.job_type = job_type
if reaction and reaction ~= '' then
    job.reaction_name = reaction
end
job.pos.x = building.centerx
job.pos.y = building.centery
job.pos.z = building.z

local ref = df.general_ref_building_holderst:new()
ref.building_id = building.id
job.general_refs:insert('#', ref)

-- A workshop only dispatches jobs that are also in its own job vector.
if building.jobs then building.jobs:insert('#', job) end

local ok, err = pcall(function() dfhack.job.linkIntoWorld(job, true) end)
if not ok then
    job:delete()
    print('failed to queue: ' .. tostring(err))
    return
end

print(json.encode({
    job_id = job.id,
    building = building.id,
    type = job_name,
    reaction = reaction or '',
    pos = { building.centerx, building.centery, building.z },
}))
