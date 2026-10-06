#!/bin/zsh
# Real-size Command Code turns three ways, interleaved per round. Key read from env, never printed. No TypeSafe.
U=https://api.commandcode.ai/provider/v1/systemone
H=(-H "Authorization: Bearer $CMD_API_KEY" -H "Content-Type: application/json" -H "User-Agent: skill-concierge")
W='%{http_code} v%{http_version} up=%{size_upload}B connect=%{time_connect} tls=%{time_appconnect} sent=%{time_pretransfer} ttfb=%{time_starttransfer} total=%{time_total}\n'
for r in {1..5}; do
  echo "== round $r"
  s=$EPOCHREALTIME
  curl -sS -o /dev/null -m 30 $H --data-binary @wide.json -w "A wide   $W" $U
  curl -sS -o /dev/null -m 30 $H --data-binary @rerank.json -w "A rerank $W" $U
  printf "A turn %.2fs\n" $(( EPOCHREALTIME - s ))
  s=$EPOCHREALTIME
  curl -sS -m 30 $H --data-binary @wide.json -o /dev/null -w "B wide   $W" $U --next -sS -m 30 $H --data-binary @rerank.json -o /dev/null -w "B rerank $W" $U
  printf "B turn %.2fs\n" $(( EPOCHREALTIME - s ))
  s=$EPOCHREALTIME
  curl -sS -m 30 --parallel --parallel-immediate \
    $H --data-binary @wide-0.json -o /dev/null -w "C w0     $W" $U --next \
    $H --data-binary @wide-1.json -o /dev/null -w "C w1     $W" $U --next \
    $H --data-binary @wide-2.json -o /dev/null -w "C w2     $W" $U
  m=$EPOCHREALTIME
  curl -sS -o /dev/null -m 30 $H --data-binary @rerank.json -w "C rerank $W" $U
  printf "C turn %.2fs (wide phase %.2fs)\n" $(( EPOCHREALTIME - s )) $(( m - s ))
done
