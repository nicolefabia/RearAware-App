# Privacy Policy for RearAware Desktop

**Last updated:** August 2026

RearAware Desktop ("the app") is a background application for macOS and Windows that detects and censors cat rear ends in your webcam feed, output through a virtual camera you can select in meeting apps like Google Meet, Microsoft Teams, and Zoom.

This policy differs from the [Chrome extension's privacy policy](https://github.com/nicolefabia/rearaware-chrome/blob/main/PRIVACY.md) in one important way: the desktop app has an optional data-collection feature the extension doesn't. Read on for exactly what that means.

## Detection: 100% on-device

Webcam frames are read directly from your camera, processed locally by an on-device AI model, composited with your chosen censor overlay, and sent to the virtual camera output. At no point does a raw or censored video frame leave your device as part of normal detection and censoring - that part works exactly like the Chrome extension.

## Help improve the model (on by default)

The app includes a feature to help train better cat-butt detection, since the model is currently trained on very few examples. **This is on by default**, and you can turn it off at any time from the "Help improve the model" toggle in Settings.

When this is on:

- When a cat is detected, the frame is cropped tightly to just the cat's bounding box - never the rest of your room, and never anyone else who happens to be in frame. Nothing outside that box is ever captured or stored.
- Captures are limited to roughly once per detection (not continuously) and capped per day, so this isn't recording a stream of your webcam.
- Cropped images are uploaded to a private cloud storage bucket, along with basic technical metadata (detection confidence scores, the model version, a timestamp, and the position of the detected area within the crop). This metadata contains no personal information.
- Every uploaded image is **manually reviewed by the developer** before it is ever used for anything. Nothing is added to model training data automatically.
- Uploaded images are not publicly accessible - the storage bucket requires authentication to read, and images aren't shared with any third party.

To turn this off: open RearAware's settings from the tray/menu bar icon and switch off "Help improve the model." No further captures or uploads happen once it's off, and anything already queued locally but not yet uploaded is discarded.

## Other data collected

- **Settings** (detection on/off, confidence threshold, censor style, sound, launch-at-login, and the contribution toggle itself) are stored locally on your device only, and never leave it.
- No account, sign-in, or personal identifier is required or collected to use the app.
- No analytics, advertising, or tracking services are used.

## Children's privacy

RearAware Desktop does not knowingly collect information from children beyond what's described above (cropped images of cats, when the contribution feature is on).

## Changes to this policy

If a future version of the app changes what's collected or how, this page will be updated and the "Last updated" date above will reflect that.

## Contact

Questions about this policy can be raised via the project's GitHub Issues page.
