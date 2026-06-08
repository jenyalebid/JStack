---
paths:
  - "**/Forms/**"
  - "**/*Form.swift"
  - "**/*Edit.swift"
  - "**/*EditView.swift"
  - "**/*Settings.swift"
  - "**/*SettingsView.swift"
---

# Forms & Input

Rules for views that collect user input — forms, edit screens, settings, and configuration flows.

## When to Use Form vs Custom Layout

| Use `Form` | Use custom layout |
|------------|-------------------|
| Settings screens | Inline editing within content |
| System-styled grouped sections | Custom-styled input (game UI, branded flows) |
| Simple field lists | Mixed content (input + preview + media) |

`Form` gives you grouped inset styling, section headers, and standard iOS form appearance for free.

## Structure

### Form in a sheet (most common)
```swift
NavigationStack {
    Form {
        Section("Details") {
            TextField("Title", text: $title)
            DatePicker("Date", selection: $date)
        }
        Section("Options") {
            Toggle("Notifications", isOn: $notificationsOn)
            Picker("Category", selection: $category) {
                ForEach(categories) { Text($0.name).tag($0) }
            }
        }
    }
    .navigationTitle("Edit")
    .navigationBarTitleDisplayMode(.inline)
    .toolbar {
        ToolbarItem(placement: .cancellationAction) {
            Button("Cancel") { dismiss() }
        }
        ToolbarItem(placement: .confirmationAction) {
            Button("Save") { save() }
                .disabled(!isValid)
        }
    }
}
```

### Settings screen (pushed via navigation)
```swift
Form {
    Section("Appearance") { /* toggles, pickers */ }
    Section("Data") { /* actions */ }
    Section("About") { /* info rows */ }
}
.navigationTitle("Settings")
```

## Input Fields

- **TextField:** Use `.textContentType()` for AutoFill (`.name`, `.emailAddress`, `.URL`, etc.)
- **SecureField:** For passwords. Pair with `.textContentType(.password)` or `.newPassword`
- **TextEditor:** For multi-line text. Give it an explicit `frame(minHeight:)` since it doesn't auto-size
- **Picker:** Use inline style for 2-5 options, navigation style for longer lists, wheel for dates/times
- **DatePicker:** `.graphical` for date selection, `.wheel` for time-only
- **Toggle:** For binary on/off settings. Use descriptive labels
- **Stepper:** For small numeric adjustments with clear bounds
- **Slider:** For continuous values in a range. Show the current value alongside

## Validation

- Validate on field exit (`.onSubmit`, focus change), not on every keystroke
- Show validation state visually — red border/text for errors, checkmark for valid
- Disable the Save/Done button when the form is invalid (`.disabled(!isValid)`)
- Keep error messages close to the field they relate to, not in a banner at the top

## Keyboard Handling

- Set appropriate keyboard type: `.keyboardType(.numberPad)`, `.emailAddress`, `.URL`
- Add `.submitLabel(.done)` or `.submitLabel(.next)` for the return key text
- Use `@FocusState` to manage focus between fields
- Dismiss keyboard when tapping outside input fields or on a "Done" toolbar button
- Forms in sheets: keyboard pushes content up automatically. Don't fight it

## Save / Cancel Flow

- **Cancel** dismisses without saving. If there are unsaved changes, show a confirmation alert
- **Save** validates → saves → dismisses. Disable while saving (show loading state on the button)
- Track changes: compare current values to initial values to know if anything changed
- `.interactiveDismissDisabled(hasChanges)` on the sheet to prevent accidental dismiss

## Destructive Actions in Forms

- Delete/reset actions go in their own section at the bottom
- Red text (`.foregroundStyle(.red)`) for destructive labels
- Always confirm before executing: `.confirmationDialog` or `.alert`

## Verification

When reviewing a form or input view:
- All fields have appropriate keyboard types and content types
- Save is disabled when form is invalid
- Cancel with unsaved changes shows confirmation
- Validation errors are visible and near the relevant field
- Keyboard doesn't obscure active input
- Required vs optional fields are clear to the user
