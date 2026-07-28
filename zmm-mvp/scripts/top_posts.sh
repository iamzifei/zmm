#!/bin/bash
# Voice calibration for /zmm-mvp: print James's own top-10 X posts by bookmark rate.
# Filters: canonical author + impressions >= 1000 (drop small-sample noise) + not a reply.
# CSV fields: role,bookmark_rate,bookmarks,impressions,url,text
CSV="$HOME/Dev/詹有才/01-原始素材区/数据/候选池/我的-JamesAI-素材候选池.csv"
awk -F, '$1=="本人(canonical)" && $4>=1000 && $6 !~ /^@/' "$CSV" | sort -t, -k2 -rn | head -10
