#!/bin/zsh
# Real-size router turns (wide + rerank) through jevd, pinned to Command Code. No TypeSafe requests.
zmodload zsh/datetime
U=http://127.0.0.1:4377/v1/systemone
H=(-H "Content-Type: application/json" -H "X-Jevd-Provider: commandcode")
W='%{http_code} %{time_total} %header{x-jevd-provider} %header{x-jevd-fell}'
gaps=(2 5 2 10 2 5 2 20 2 5 2 30)
for i in {1..12}; do
  s=$EPOCHREALTIME
  w=$(curl -sS -o /dev/null -m 15 $H --data-binary @wide.json -w "$W" $U)
  r=$(curl -sS -o /dev/null -m 15 $H --data-binary @rerank.json -w "$W" $U)
  printf "turn %2d: %.2fs | wide [%s] | rerank [%s]\n" $i $(( EPOCHREALTIME - s )) "$w" "$r"
  sleep $gaps[$i]
done
