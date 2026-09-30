# Research: Microsoft UI Automation (UIA) Architecture

## 1. What UI Automation Is
Microsoft UI Automation (UIA) is the native accessibility framework for Windows (Windows 10 & 11). It exposes all graphical user interface elements to assistive technologies via a hierarchical tree of `AutomationElement` nodes, abstracting away framework differences between Win32, WinForms, WPF, UWP/WinUI, and Chromium.

## 2. Core Architecture & Interfaces
- **`IUIAutomation`**: The main entry point COM interface (created with `CoCreateInstance(CLSID_CUIAutomation8)`).
- **`IUIAutomationElement`**: Represents an individual UI component (window, button, edit box, list item).
- **Tree Views**:
  - *Raw View*: The complete hierarchy including non-interactive grouping containers.
  - *Control View*: Elements that provide user interaction (buttons, inputs, menus). Preferred for perception.
  - *Content View*: Elements that contain actual readable information (text, list items). Preferred for document reading.
- **`IUIAutomationTreeWalker`**: Efficiently walks siblings and parent/child hierarchies using pre-filtered conditions.

## 3. Key Control Patterns
Rather than guessing screen coordinates or synthesizing imprecise mouse clicks, UIA provides programmatic control patterns:
- **`InvokePattern` (`UIA_InvokePatternId`)**: Directly triggers buttons, hyperlinks, and menu items without moving the physical mouse pointer.
- **`ValuePattern` (`UIA_ValuePatternId`)**: Reads and sets text values in edit boxes instantaneously.
- **`TextPattern` / `TextPattern2` (`UIA_TextPatternId`)**: Provides range-based document navigation (by character, word, line, paragraph, or page) for Notepad, Word, Edge, and PDF viewers.
- **`SelectionPattern` / `SelectionItemPattern`**: Reads and selects items in lists, comboboxes, and tab strips.
- **`TogglePattern` / `ExpandCollapsePattern`**: Operates checkboxes, tree views, and disclosure widgets.
- **`WindowPattern`**: Controls window state (minimize, maximize, close) safely without process termination.

## 4. Event Subscriptions vs. Polling
Continuous polling of the desktop UI tree degrades CPU performance and introduces latency. UIA provides native event callbacks:
- **`IUIAutomationFocusChangedEventHandler`**: Fires whenever focus shifts between elements.
- **`IUIAutomationPropertyChangedEventHandler`**: Fires on specific property changes (e.g., `Name`, `ToggleState`, `Value`).
- **`IUIAutomationStructureChangedEventHandler`**: Fires when windows or dialogs open, close, or rearrange.

### Best Practice: Scope Bounding
Never subscribe to structure changes across the entire desktop root (`TreeScope_Subtree`). Instead, listen to focus changes globally, then attach property/structure listeners scoped strictly to the current foreground window (`TreeScope_Children`).

## 5. Performance Optimization: `IUIAutomationCacheRequest`
Each property query over COM across processes costs ~0.5–2 ms of IPC overhead. A single element requiring Name, ControlType, AutomationId, BoundingRectangle, and ValuePattern would require 5 separate round trips.
- **The Solution**: Construct an `IUIAutomationCacheRequest`.
- Pre-register all required properties and patterns.
- Query elements with `FindFirstBuildCache()` or `BuildUpdatedCache()`.
- Reads are then serviced instantly from local process memory in a single round trip.

## 6. Licensing & Dependencies
- Core Windows System Component: `UIAutomationCore.dll`.
- Accessible from Python via `comtypes` or `ctypes` under standard MIT licensing.
- Official Microsoft Docs: https://learn.microsoft.com/en-us/windows/win32/winauto/entry-uiauto-win32
