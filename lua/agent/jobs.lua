-- agent/jobs - list queued jobs as JSON
local json = require('json')
local utils = require('utils')
local args = { ... }
local limit = tonumber(args[1]) or 50

local jobs = {}
for _, job in utils.listpairs(df.global.world.jobs.list) do
    local worker = dfhack.job.getWorker(job)
    jobs[#jobs + 1] = {
        type = df.job_type[job.job_type] or tostring(job.job_type),
        pos = { job.pos.x, job.pos.y, job.pos.z },
        worker = worker and worker.id or nil,
        wait = job.wait_timer,
    }
    if #jobs >= limit then break end
end

local counts = {}
for _, job in ipairs(jobs) do
    counts[job.type] = (counts[job.type] or 0) + 1
end

print(json.encode({ total = #jobs, counts = counts, jobs = jobs }))
