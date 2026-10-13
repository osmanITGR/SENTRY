# SENTRY Tactical Control

Project SENTRY EOD রোবটের জন্য Tactical HUD ও কন্ট্রোল অ্যাপ — Android মোবাইল ও Windows ডেস্কটপ।

Tactical HUD and control application for the Project SENTRY EOD robot, for Android and Windows.

## ডাউনলোড / Download

সর্বশেষ ভার্সন: **[Releases](https://github.com/osmanITGR/SENTRY/releases/latest)**

| প্ল্যাটফর্ম | ফাইল |
|---|---|
| Android (মোবাইল) | `SENTRY_Tactical_Control_v<ভার্সন>.apk` |
| Windows 10/11 (64-bit) | `SENTRY_Tactical_Control_Setup_v<ভার্সন>.exe` |

## Android-এ ইন্সটল

1. Releases থেকে `.apk` ফাইলটি ফোনে ডাউনলোড করুন।
2. ফাইলটি খুলুন। "Install unknown apps" অনুমতি চাইলে ব্রাউজার/ফাইল ম্যানেজারকে অনুমতি দিন।
3. **Install** চাপুন।

## Windows-এ ইন্সটল

1. Releases থেকে `Setup_v<ভার্সন>.exe` ডাউনলোড করে চালান।
2. ইনস্টলার কোড-সাইন করা নয়, তাই SmartScreen "Windows protected your PC" দেখাতে পারে →
   **More info** → **Run anyway**।
3. Start Menu-তে **SENTRY Tactical Control** ও **SENTRY USB Bridge** যুক্ত হবে।

সাইলেন্ট ইনস্টল:

```
SENTRY_Tactical_Control_Setup_vX.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

মিশন লগ ও স্ক্যান-ফলাফল থাকে `%APPDATA%\Lcpl Osman Gani\SENTRY Tactical Control\` ফোল্ডারে।
আনইনস্টল করলেও এই ডেটা মুছে যায় না।

## ব্যবহার

1. রোবট অন করুন।
2. ফোন/ল্যাপটপের Wi-Fi থেকে রোবটের `SENTRY_NET` নেটওয়ার্কে যুক্ত হন।
3. অ্যাপ খুলুন। সেন্সর ডেটা ও ক্যামেরা স্ট্রিম নিজে থেকেই আসবে।

**USB কেবলে (Windows):** রোবটের USB ল্যাপটপে লাগান, Start Menu থেকে **SENTRY USB Bridge** চালান,
তারপর অ্যাপ খুলুন (127.0.0.1:8080-এ নিজে যুক্ত হয়)। এ সময় Arduino Serial Monitor বন্ধ রাখুন।

## ফাইল যাচাই (SHA-256)

প্রতিটি রিলিজের নোটে ফাইলগুলোর SHA-256 হ্যাশ দেওয়া আছে। Windows-এ যাচাই করতে:

```
certutil -hashfile SENTRY_Tactical_Control_Setup_vX.exe SHA256
```

---

© Lcpl Osman Gani
