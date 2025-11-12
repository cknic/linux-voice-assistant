# Fork Integration Information

This is a "best-of-breed" integration fork combining features from multiple sources.

## Remote Repositories

- **upstream** (OHF-Voice): Main upstream repository
  - https://github.com/OHF-Voice/linux-voice-assistant
  
- **omar**: Omar's fork with thinking sound features
  - https://github.com/omaramin-2000/linux-voice-assistant
  
- **imonlinux**: Imonlinux's fork with LED/MQTT/ReSpeaker support
  - https://github.com/imonlinux/linux-voice-assistant

- **origin**: Your integrated fork
  - https://github.com/cknic/linux-voice-assistant

## Branches

- `main`: Tracks upstream/main (OHF-Voice official)
- `integration`: Your merged "best-of-breed" version with features from Omar and Imonlinux

## Clone and Setup

```bash
# Clone from your fork
git clone https://github.com/cknic/linux-voice-assistant.git
cd linux-voice-assistant

# Add upstream remotes
git remote add upstream https://github.com/OHF-Voice/linux-voice-assistant.git
git remote add omar https://github.com/omaramin-2000/linux-voice-assistant.git
git remote add imonlinux https://github.com/imonlinux/linux-voice-assistant.git

# Fetch all
git fetch --all

# Use the integration branch
git checkout integration
