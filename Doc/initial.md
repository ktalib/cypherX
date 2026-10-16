# PROJECT: CYBEROPS — FUTURISTIC WINDOWS DESKTOP COMMAND CENTER

## 1. Project Objective

Build a complete, futuristic, sci-fi-inspired Windows desktop application using Python. The application should function as a personal PC command center, combining a high-tech cyberpunk interface with practical Windows system utilities, file management, storage analysis, productivity tools, and automation.

Use the attached screenshot as the primary visual reference.

The interface should resemble a futuristic computer operations terminal from a science-fiction movie: dark panels, neon cyan and green accents, real-time system statistics, terminal logs, network visualizations, animated status indicators, progress bars, and a sophisticated dashboard layout.

**Important:** This must be a functional desktop utility, not a static mockup. Every implemented button, tool, menu, and interactive panel must perform its advertised function.

The application should run locally on Windows 10 and Windows 11.

## 2. Technology Stack

Use the following technologies unless there is a strong technical reason to change them:

- Python 3.12 or a compatible installed Python version.
- PySide6 for the desktop GUI.
- Qt Widgets for the main interface, dialogs, tables, menus, and forms.
- Qt Charts or custom-painted charts for system telemetry.
- psutil for CPU, memory, disk, process, and network monitoring.
- pathlib and shutil for safe file operations.
- send2trash for moving files to the Recycle Bin.
- sqlite3 for local application settings, operation history, and user preferences.
- QThread or QThreadPool for background tasks so the interface never freezes.
- QTimer for live clock updates and periodic system monitoring.
- Windows-specific APIs or carefully selected Python libraries when required for Windows functionality.

Use native Windows functionality where appropriate.

Avoid unnecessary dependencies, excessive memory consumption, and complicated installation requirements.

Create a requirements.txt file and a README.md with installation and usage instructions.

## 3. Visual Design System

Reproduce the general visual language of the supplied screenshot.

### Theme

- Background: almost-black charcoal with a slight blue-green tint.
- Panel background: dark green-black.
- Primary accent: neon cyan.
- Secondary accent: bright terminal green.
- Text: muted gray-green for secondary information and bright cyan or green for important information.
- Borders: thin, subtle green-gray outlines.
- Typography: monospace fonts such as Consolas, Cascadia Mono, or JetBrains Mono.
- Optional headings: a restrained futuristic display font.

Use a consistent color system throughout the application.

### Interface details

- Thin bordered panels with compact headers.
- Small uppercase section labels with subtle letter spacing.
- Animated green online indicators.
- Smooth progress bars and system graphs.
- Scrolling terminal output.
- Responsive resizing without overlapping widgets.
- Clear visual distinction between active, inactive, warning, and error states.
- Subtle hover effects and transitions.
- Consistent icons and spacing.
- Custom dialogs that match the theme.
- Optional sound effects, disabled by default.

Avoid excessive glow effects, large rounded cards, unnecessary gradients, and oversized dashboard elements. The interface should feel like a professional cyber operations console.

Support full-screen mode, maximized mode, and a normal resizable window.

## 4. Main Application Layout

Create a persistent main window with the following structure.

### A. Top Status Bar

Display:

- CYBEROPS logo or application name.
- System status: ONLINE, WARNING, or OFFLINE.
- Live session duration.
- Current hostname.
- Windows version.
- Current date and digital clock.
- Active theme.
- Notifications indicator.

All system information must come from actual Windows data where possible. Do not display fabricated system readings.

### B. Left Navigation Sidebar

Create collapsible navigation with the following modules:

1. Command Center
2. My Computer
3. Disk Analyzer
4. Disk Cleaner
5. Folder Organizer
6. File Explorer
7. Duplicate Finder
8. Large File Finder
9. Process Manager
10. Startup Manager
11. System Monitor
12. Network Monitor
13. Clock and Calendar
14. Notes and Tasks
15. Application Launcher
16. Automation Center
17. Operation History
18. Settings

The sidebar should remain accessible throughout the application.

Selecting an item should open the corresponding functional page without unnecessarily recreating the entire application window.

### C. Main Workspace

Use a flexible panel-based layout inspired by the screenshot.

The Command Center should contain:

- System event log.
- System resource graphs.
- Disk usage overview.
- Network activity.
- CPU and RAM utilization.
- Recent files and operations.
- Active tasks and progress.
- Clock and calendar preview.
- Quick-action buttons.

Allow dashboard panels to be rearranged or resized if practical.

### D. Right Information Panel

Display live system information:

- Operating system.
- Computer name.
- CPU model and logical processor count.
- RAM total, used, and available.
- Screen resolution.
- System uptime.
- Disk capacity and free space.
- Network interface and connection status.
- Download and upload rates.
- Current local time and timezone.

Only show information that can actually be retrieved. Display N/A when a value is unavailable.

## 5. Module: Disk Analyzer

Build a functional disk-space analysis tool.

Features:

- Detect available Windows drives.
- Display total capacity, used space, and free space.
- Scan user-selected folders.
- Calculate folder sizes recursively.
- Identify the largest folders and files.
- Sort results by size, filename, extension, and modified date.
- Display folder-size distribution with bar charts or treemaps.
- Show file extensions consuming the most storage.
- Filter by file type, size, and date.
- Allow opening a file or its containing folder.
- Export scan results to CSV.

Use a background worker for long scans.

Provide pause or cancel functionality where practical.

Do not scan protected system directories automatically. Require explicit user selection before analyzing potentially sensitive or large system locations.

## 6. Module: Disk Cleaner

Create a safe disk-cleaning utility.

Features:

- Analyze temporary folders.
- Identify eligible application cache files.
- Identify old temporary files.
- Find eligible files in the Windows and user temporary directories.
- Show file size, location, and last modified date.
- Calculate the total potential space recovery.
- Let users select individual categories or files.
- Provide a preview before cleanup.
- Show progress and a summary after completion.

Safety requirements:

- Analysis must never delete files.
- Cleanup must require explicit user confirmation.
- Prefer moving user files to the Recycle Bin using send2trash.
- For temporary files that cannot be moved to the Recycle Bin, explain the deletion behavior before proceeding.
- Skip files that are locked, inaccessible, or actively used.
- Never delete arbitrary files based only on filename or extension.
- Never delete personal documents, browser profiles, saved passwords, application databases, or system-critical files.
- Never silently clean Downloads, Desktop, Documents, or other personal folders.
- Never execute destructive cleanup automatically at startup.
- Do not run commands such as format, diskpart clean, or recursive deletion against broad system paths.

Display the number of files processed, skipped, and removed, along with errors.

## 7. Module: Folder Organizer

Build an intelligent file organization tool.

Users must be able to select a folder and configure organization rules.

Supported organization methods:

- By file extension.
- By category.
- By file creation date.
- By last modified date.
- By year and month.
- By custom naming patterns.
- By user-defined rules.

Example categories:

- Documents
- Images
- Videos
- Audio
- Archives
- Installers
- Spreadsheets
- Presentations
- Code
- Other

Example:

Before:

Downloads/
  invoice.pdf
  holiday.jpg
  presentation.pptx
  archive.zip
  recording.mp3

After:

Downloads/
  Documents/invoice.pdf
  Images/holiday.jpg
  Presentations/presentation.pptx
  Archives/archive.zip
  Audio/recording.mp3

Required safeguards:

- Preview every planned move.
- Display the source and destination paths.
- Detect naming conflicts.
- Never overwrite files silently.
- Provide conflict resolution options.
- Default to a dry run.
- Require confirmation before executing moves.
- Record completed operations.
- Provide an undo option where the original state can safely be restored.
- Never move files outside the selected root directory unless explicitly configured.

Do not use AI or an external API unnecessarily. Begin with predictable, rule-based organization.

## 8. Module: Duplicate Finder

Implement duplicate-file detection.

Features:

- Scan selected directories.
- Compare file sizes first.
- Use SHA-256 hashing to verify duplicates.
- Group identical files.
- Display each file's path, size, and modified date.
- Calculate total duplicate storage.
- Allow the user to select files for removal.
- Provide a safe preview.
- Prefer Recycle Bin operations.
- Exclude the first or designated reference copy by default.
- Log all actions.

Never assume that files with identical names are duplicates.

## 9. Module: Large File Finder

Find storage-consuming files.

Features:

- Scan user-selected locations.
- Configure minimum file size.
- Preset filters such as 100 MB, 500 MB, 1 GB, and 5 GB.
- Filter by extension and modification date.
- Sort by file size.
- Open the containing folder.
- Display the total size of selected results.
- Export reports to CSV.

Do not automatically delete large files.

## 10. Module: Live System Monitor

Build a real-time monitoring dashboard.

Display:

- CPU utilization.
- RAM usage.
- Disk usage.
- Disk read and write activity.
- Network upload and download rates.
- System uptime.
- CPU core count.
- Available drive capacity.
- Running process count.

Use historical line graphs for CPU, RAM, and network traffic.

Allow users to change the monitoring refresh interval.

The display must use real measurements, not random numbers or hardcoded demo data.

Ensure that monitoring does not consume excessive CPU or memory.

## 11. Module: Process Manager

Display running Windows processes.

Columns:

- S/N
- Process name
- PID
- CPU utilization
- Memory usage
- Executable path, when accessible
- Process status

Features:

- Search and filter.
- Sort by CPU and memory.
- Refresh process information.
- View process details.
- Open the executable location when accessible.

Terminating a process must require confirmation.

Protect critical Windows processes from termination through the normal interface. Handle access-denied errors gracefully.

Do not implement arbitrary process injection, credential extraction, stealth monitoring, or other offensive security functionality.

## 12. Module: Startup Manager

Display applications configured to run at Windows startup.

Show:

- Application name.
- Command or target path.
- Startup source.
- Enabled or disabled status, where determinable.

Allow safe management of supported startup entries with confirmation.

Before changing an entry, preserve its original configuration and explain how to restore it.

Do not modify startup settings without explicit user approval.

## 13. Module: Clock and Calendar

Create a dedicated futuristic clock and productivity page.

Include:

- Large digital clock.
- 12-hour and 24-hour display modes.
- Current date.
- Day of the week.
- Monthly calendar.
- Week number.
- Local timezone.
- Optional world clocks.
- Stopwatch.
- Countdown timer.
- Alarm notifications.
- Notes and reminders.
- Daily task list.

Use the computer's actual local time.

Allow users to navigate between months and years.

Store user-created tasks, notes, and reminders locally in SQLite.

For alarms and reminders, show desktop notifications when supported.

Make the clock page visually impressive without slowing down the rest of the application.

## 14. Module: File Explorer

Build a practical file-navigation interface.

Features:

- Browse drives and folders.
- Navigate backward and forward.
- Breadcrumb navigation.
- Search filenames.
- Display file size, type, and modification date.
- Open files with their default Windows applications.
- Open folders in Windows Explorer.
- Copy paths to the clipboard.
- Support standard file-selection dialogs.

For the first version, prioritize browsing, viewing, and opening files rather than recreating every Windows Explorer feature.

## 15. Module: Application Launcher

Create a searchable application launcher.

Features:

- Add favorite applications.
- Search configured application paths.
- Launch approved executables.
- Open frequently used folders.
- Support configurable keyboard shortcuts.
- Store favorites locally.
- Allow users to edit or remove shortcuts.

Never execute commands from untrusted files or automatically run downloaded programs.

## 16. Module: Network Monitor

Display real local network telemetry:

- Available network interfaces.
- Connection status.
- Local IP address where available.
- Upload and download rates.
- Bytes sent and received.
- Network adapter information.

Do not perform unauthorized port scanning, credential probing, exploitation, or remote intrusion.

Do not present fabricated network nodes or simulated external connections as real devices.

If a decorative network map is included, label simulated elements clearly.

## 17. Module: Automation Center

Create a simple rule-based automation interface.

Allow users to configure tasks such as:

- Organize a selected folder manually or on a schedule.
- Generate periodic storage reports.
- Remind users to review low disk space.
- Display reminders at a configured time.
- Open selected applications through user-approved shortcuts.

Every automation must be visible, editable, and disableable.

Never schedule destructive file deletion or system modifications without a separate confirmation mechanism.

Avoid hidden background services. Explain any optional Windows startup integration.

## 18. Module: Operation History

Maintain a searchable local history of actions.

Record:

- Timestamp.
- Operation type.
- Selected folder or file.
- Action performed.
- Result.
- Errors or skipped items.
- Whether the operation can be undone.

Allow users to filter the history and export reports.

Store only the information necessary for the application's functionality.

Provide a setting to clear operation history.

## 19. Settings

Include:

- Theme customization.
- Accent color.
- Font size.
- Clock format.
- Refresh intervals.
- Default scan locations.
- Default file organization rules.
- Confirmation preferences.
- Notification settings.
- Startup behavior.
- Log retention.
- Database location.
- Export settings.

Use persistent local settings.

Keep the default configuration safe and conservative.

## 20. Application Architecture

Use a modular project structure similar to:

cyberops/
  main.py
  requirements.txt
  README.md
  app/
    __init__.py
    config.py
    database.py
    theme.py
    main_window.py
    navigation.py
    workers/
      __init__.py
      scan_worker.py
      cleanup_worker.py
      organize_worker.py
      monitor_worker.py
    services/
      system_service.py
      disk_service.py
      cleanup_service.py
      file_organizer_service.py
      duplicate_service.py
      process_service.py
      network_service.py
      notification_service.py
    views/
      dashboard.py
      disk_analyzer.py
      disk_cleaner.py
      folder_organizer.py
      duplicate_finder.py
      large_file_finder.py
      system_monitor.py
      process_manager.py
      startup_manager.py
      file_explorer.py
      clock_calendar.py
      application_launcher.py
      network_monitor.py
      automation_center.py
      operation_history.py
      settings.py
    widgets/
      status_bar.py
      terminal_panel.py
      metric_card.py
      progress_panel.py
      clock_widget.py
      calendar_widget.py
      chart_widget.py
      confirmation_dialog.py
    tests/
      test_file_organizer.py
      test_duplicate_finder.py
      test_cleanup_safety.py

You may improve this structure if needed, but keep the application modular and maintainable.

Do not put the entire application in one Python file.

Keep file operations and system logic separate from GUI code.

## 21. Performance and Reliability

- Use background workers for directory scans and long-running tasks.
- Keep the GUI responsive.
- Support cancellation where practical.
- Handle permission errors and missing files.
- Handle disconnected drives.
- Prevent duplicate worker execution.
- Validate user inputs.
- Avoid loading enormous directory listings into memory all at once.
- Avoid repeated expensive recursive scans on every dashboard refresh.
- Ensure workers are stopped cleanly when the application closes.
- Add logging and useful error messages.
- Avoid requiring administrator privileges for ordinary functionality.
- Request elevated privileges only for a specific feature that genuinely needs them.

## 22. Testing and Verification

Implement and test features incrementally.

At minimum, verify:

1. The application launches successfully.
2. The dashboard displays real system data.
3. The clock updates correctly.
4. Disk analysis returns correct results.
5. The cleaner performs analysis without deleting anything.
6. Cleanup requires confirmation.
7. Folder organization supports dry-run previews.
8. File conflicts never cause silent overwrites.
9. Duplicate detection verifies file content.
10. Long-running operations do not freeze the interface.
11. Cancellation works where supported.
12. Operation history records completed actions.
13. The application handles inaccessible files gracefully.
14. The application closes without leaving workers running.
15. The interface remains usable at different window sizes.

Use temporary test directories for file-operation tests. Never test destructive functions against actual user folders.

## 23. Packaging

Prepare the application for local Windows use.

Provide:

- requirements.txt
- README.md
- A virtual-environment setup guide.
- Installation instructions.
- A launch script such as run.bat.
- Optional PyInstaller packaging instructions.
- An application icon if practical.
- Clear troubleshooting instructions.

The application should be usable without requiring the user to understand Python internals.

## 24. Development Instructions

Before writing code:

1. Inspect the existing project directory.
2. Check the installed Python version and available dependencies.
3. Determine whether an existing application or project must be preserved.
4. Present the proposed architecture and implementation plan.
5. Identify dependencies that need installation.

Then implement the application in working stages.

### Stage 1
Build the main window, theme, sidebar, status bar, clock, dashboard layout, and real system metrics.

### Stage 2
Implement Disk Analyzer, Large File Finder, and System Monitor.

### Stage 3
Implement Disk Cleaner with strict safety protections.

### Stage 4
Implement Folder Organizer with dry-run preview, conflict handling, and undo support.

### Stage 5
Implement Duplicate Finder, File Explorer, Process Manager, and Startup Manager.

### Stage 6
Implement Calendar, reminders, Application Launcher, Network Monitor, and Automation Center.

### Stage 7
Complete settings, history, tests, error handling, and Windows packaging.

After each stage, run the application and relevant tests before continuing.

Do not replace working features with mockups. Do not mark a feature complete until its actual functionality has been tested.

If a feature cannot be implemented reliably, explain the limitation rather than presenting a nonfunctional control.

## Final Deliverable

Deliver a working, polished, futuristic Windows desktop command center called CYBEROPS.

The finished application must combine the visual quality of the reference screenshot with genuinely useful PC utilities, safe file management, live system telemetry, and productivity tools.

Prioritize stability, real functionality, safety, performance, and a consistent sci-fi visual identity.