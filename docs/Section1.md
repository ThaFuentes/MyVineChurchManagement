# Section 1: The Vision & Core Mission

## The "What" and "Why"

MyVineChurch.Online is a unified digital ecosystem designed to serve a local church body in both its spiritual and logistical dimensions.

The vision is simple but ambitious: to create a single, lightweight, secure platform where:
- The internal spiritual life of the church (prayer, prophecy, dreams, sermon preparation, pastoral care) is nurtured and tracked.
- The external community life (public dashboard, announcements, events, online giving) is welcomed and engaged.
- The administrative life (membership, finances, inventory, attendance, ticketing) is managed with integrity and minimal friction.

This is not a generic church management system. It is custom-built for a specific congregation that values:
- Spiritual intelligence (tracking revelations, dreams, prophecies)
- Pastoral efficiency (sermon builder, podium teleprompter, care tracking)
- Community connection (The Gathering Place public view)
- Financial transparency (donation tracking, recurring bill reminders – no payment processing)
- Data sovereignty (local MariaDB, encrypted credentials, audit logs)

## The "No-Bloat" Architecture Philosophy

We deliberately chose a stack that is:
- **Lightweight**: Flask + MariaDB + vanilla JS/Bootstrap
- **Maintainable**: Clean blueprint structure, explicit imports, no magic
- **Secure**: @pastoral_required decorator, hashed pins, IP banning, encrypted email settings
- **Extensible**: Every major feature is its own blueprint, models are modular, templates inherit from base

The result is a system that:
- Runs on a single server or Raspberry Pi
- Requires no external SaaS dependencies
- Can be fully backed up with one database file
- Is readable and modifiable by a single developer (you)

## Core Principles That Guided Every Decision

1. **Spiritual First** – Tools for prophecy, dreams, prayer, and sermon preparation are as prominent as administrative tools.
2. **Public/Private Separation** – The Gathering Place is welcoming and safe; the Pastoral Command Center is locked down.
3. **User Experience for Busy Pastors** – Podium Mode, one-click planning, instant reorder, font persistence.
4. **Data Ownership** – Everything lives in your MariaDB instance. No third-party lock-in.
5. **Audit Everything** – log_change tracks every significant action for accountability.
