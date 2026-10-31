# Precision Skill Suite (১৩টি skill)

Claude Code-এর কাজ নিখুঁত, দ্রুত ও যাচাইকৃত করার জন্য project-level skills।
এই repo-তে Claude যেকোনো কাজ শুরু করলে `precision-workflow` থেকে শুরু হয় (দেখুন `/CLAUDE.md`)।

| # | Skill | কাজ |
|---|-------|-----|
| 1 | `precision-workflow` | মূল পাইপলাইন: প্রতিটি ধাপের "gate" — পাস না করলে পরের ধাপ নয় |
| 2 | `task-intake` | অনুরোধকে যাচাইযোগ্য acceptance criteria-তে রূপান্তর, scope নির্ধারণ |
| 3 | `codebase-recon` | সঠিক file:line খুঁজে বের করা, stack ও আসল test/build কমান্ড শনাক্ত |
| 4 | `modern-integration` | প্রজেক্টের ইনস্টল করা ভার্সন অনুযায়ী আধুনিক, deprecated-মুক্ত কোড |
| 5 | `legacy-cleanup` | পুরাতন/অব্যবহৃত কোড প্রমাণসহ নিরাপদে মুছে ফেলা |
| 6 | `safe-refactor` | আচরণ না বদলে কাঠামো পরিবর্তন |
| 7 | `root-cause-debug` | অনুমান নয় — reproduce → isolate → মূল কারণ → regression test |
| 8 | `test-strategy` | edge/boundary/error/regression/platform — সর্বমুখী টেস্ট ম্যাট্রিক্স |
| 9 | `verification-gate` | সব lint/typecheck/build/test চালিয়ে সৎ PASS/FAIL/UNVERIFIED রায় |
| 10 | `self-review` | commit-এর আগে নিজের diff লাইন ধরে রিভিউ |
| 11 | `efficiency-guard` | সময় নষ্ট রোধ: parallel কাজ, লক্ষ্যভিত্তিক পড়া, loop-breaker |
| 12 | `dependency-upgrade` | changelog পড়ে নিরাপদে ভার্সন আপগ্রেড ও মাইগ্রেশন |
| 13 | `git-delivery` | পরিচ্ছন্ন commit, নিরাপদ push, সৎ রিপোর্ট |

## স্ক্রিপ্ট (অনুমান নয়, নির্দিষ্ট ফলাফল)

```bash
# কোন প্রজেক্ট, কোন stack, কোন কমান্ড (Node/Python/Go/Rust/Flutter/Android/.NET/Arduino/PlatformIO, monorepo সহ)
python3 .claude/skills/codebase-recon/scripts/detect_stack.py

# সব চেক চালিয়ে রায় (exit 0=PASS, 1=FAIL, 2=UNVERIFIED)
python3 .claude/skills/verification-gate/scripts/verify.py --changed

# অব্যবহৃত symbol, orphan ফাইল, deprecated মার্কার, comment-করা কোড
python3 .claude/skills/legacy-cleanup/scripts/find_dead_code.py --path src/

# পুরো suite-এর নিজস্ব টেস্ট (১০০+ assertion)
python3 .claude/skills/precision-workflow/scripts/selftest.py
```

শুধু Python 3 standard library লাগে; বাড়তি কিছু ইনস্টল করতে হয় না।
