const vscode = require('vscode');
const { LanguageClient, TransportKind } = require('vscode-languageclient/node');
const path = require('path');
const fs = require('fs');
const cp = require('child_process');

/** @type {LanguageClient | null} */
let client = null;
/** @type {vscode.StatusBarItem | null} */
let statusBarItem = null;
/** @type {vscode.TestController | null} */
let testController = null;

function getPythonPath() {
    const config = vscode.workspace.getConfiguration('greengold');
    return config.get('pythonPath') || 'python';
}

function onPath(name) {
    const exts = process.platform === 'win32' ? ['.exe', '.cmd', '.bat'] : [''];
    for (const dir of (process.env.PATH || '').split(path.delimiter)) {
        if (!dir) continue;
        for (const ext of exts) {
            const file = path.join(dir, name + ext);
            try {
                if (fs.statSync(file).isFile()) return file;
            } catch (e) { /* not here */ }
        }
    }
    return null;
}

/**
 * How to run the compiler: { cmd, pre } where pre are the leading arguments.
 * Order: the `greengold.path` setting, `gg` on PATH, the folder the installers use,
 * and last `python -m greengold` (a pip or source install).
 */
function ggInvocation() {
    const configured = vscode.workspace.getConfiguration('greengold').get('path');
    if (configured) return { cmd: configured, pre: [] };
    const found = onPath('gg');
    if (found) return { cmd: found, pre: [] };
    const home = require('os').homedir();
    const installed = process.platform === 'win32'
        ? path.join(process.env.LOCALAPPDATA || path.join(home, 'AppData', 'Local'), 'Greengold', 'bin', 'gg.exe')
        : path.join(home, '.greengold', 'bin', 'gg');
    if (fs.existsSync(installed)) return { cmd: installed, pre: [] };
    return { cmd: getPythonPath(), pre: ['-m', 'greengold'] };
}

/** The same as a shell command prefix, for terminals and tasks. */
function ggShell(gg = ggInvocation()) {
    const quote = (part) => (/[\s"]/.test(part) ? `"${part.replace(/"/g, '\\"')}"` : part);
    const text = [gg.cmd, ...gg.pre].map(quote).join(' ');
    // PowerShell needs the call operator in front of a quoted program path.
    return process.platform === 'win32' && text.startsWith('"') ? `& ${text}` : text;
}

function notInstalledHint() {
    vscode.window.showErrorMessage(
        'Greengold: could not start `gg`. Install it, or set "greengold.path".',
        'Install instructions'
    ).then((choice) => {
        if (choice) vscode.env.openExternal(vscode.Uri.parse('https://github.com/Greengold-Lang/greengold-lang#install'));
    });
}

function activate(context) {
    console.log('Greengold Language Support activating...');

    // 1. Status Bar Item
    statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBarItem.command = 'greengold.showMenu';
    context.subscriptions.push(statusBarItem);

    // 2. Register Commands
    registerCommands(context);

    // 3. Register CodeLens Provider
    if (vscode.workspace.getConfiguration('greengold').get('codeLens.enable', true)) {
        registerCodeLens(context);
    }

    // 4. Register Test Controller
    if (vscode.workspace.getConfiguration('greengold').get('testing.enable', true)) {
        registerTestController(context);
    }

    // 5. Register Task Provider
    registerTaskProvider(context);

    // 6. LSP Startup
    const config = vscode.workspace.getConfiguration('greengold');
    if (config.get('languageServer.enable', true)) {
        startLanguageServer(context);
    }

    // 7. Watch configuration changes
    context.subscriptions.push(
        vscode.workspace.onDidChangeConfiguration(async (e) => {
            if (e.affectsConfiguration('greengold.languageServer') || e.affectsConfiguration('greengold.pythonPath') || e.affectsConfiguration('greengold.path')) {
                const cfg = vscode.workspace.getConfiguration('greengold');
                if (cfg.get('languageServer.enable', true)) {
                    await restartLanguageServer(context);
                } else {
                    await stopLanguageServer();
                }
            }
        })
    );

    console.log('Greengold Language Support activated successfully.');
}

// --- Command Registrations ---------------------------------------------------

function registerCommands(context) {
    context.subscriptions.push(
        vscode.commands.registerCommand('greengold.restartServer', async () => {
            await restartLanguageServer(context);
        }),
        vscode.commands.registerCommand('greengold.runFile', () => {
            executeTerminalCommand('run');
        }),
        vscode.commands.registerCommand('greengold.runRelease', () => {
            executeTerminalCommand('run', ['--release']);
        }),
        vscode.commands.registerCommand('greengold.debugFile', async (fileUri) => {
            await debugCurrentFile(fileUri);
        }),
        vscode.commands.registerCommand('greengold.buildFile', () => {
            executeTerminalCommand('build');
        }),
        vscode.commands.registerCommand('greengold.buildRelease', () => {
            executeTerminalCommand('build', ['--release']);
        }),
        vscode.commands.registerCommand('greengold.emitLLVM', () => {
            executeTerminalCommand('emit-ll');
        }),
        vscode.commands.registerCommand('greengold.emitBC', () => {
            executeTerminalCommand('emit-bc');
        }),
        vscode.commands.registerCommand('greengold.showAst', () => {
            executeTerminalCommand('ast');
        }),
        vscode.commands.registerCommand('greengold.checkFile', () => {
            executeTerminalCommand('check');
        }),
        vscode.commands.registerCommand('greengold.fixFile', () => {
            executeTerminalCommand('fix');
        }),
        vscode.commands.registerCommand('greengold.explain', async () => {
            const code = await vscode.window.showInputBox({
                prompt: 'Diagnostic code',
                placeHolder: 'GG0301',
                validateInput: (value) => /^GG\d{4}$/i.test((value || '').trim()) ? null : 'Write a code such as GG0301'
            });
            if (!code) return;
            runInTerminal(['explain', code.trim()]);
        }),
        vscode.commands.registerCommand('greengold.targets', () => {
            runInTerminal(['targets']);
        }),
        vscode.commands.registerCommand('greengold.apiLock', () => {
            runInTerminal(['api', '--lock']);
        }),
        vscode.commands.registerCommand('greengold.apiCheck', () => {
            runInTerminal(['api', '--check']);
        }),
        vscode.commands.registerCommand('greengold.formatFile', () => {
            executeTerminalCommand('fmt');
        }),
        vscode.commands.registerCommand('greengold.runTests', () => {
            executeTerminalCommand('test');
        }),
        vscode.commands.registerCommand('greengold.runSingleTest', async (fileUri, testName) => {
            await runSingleTestCommand(fileUri, testName);
        }),
        vscode.commands.registerCommand('greengold.generateDoc', () => {
            executeTerminalCommand('doc');
        }),
        vscode.commands.registerCommand('greengold.newPackage', async () => {
            await createNewPackage();
        }),
        vscode.commands.registerCommand('greengold.bindgen', async (uri) => {
            await generateBindings(uri, false);
        }),
        vscode.commands.registerCommand('greengold.bindgenCpp', async (uri) => {
            await generateBindings(uri, true);
        }),
        vscode.commands.registerCommand('greengold.showMenu', async () => {
            await showQuickMenu(context);
        })
    );
}

// --- Quick Menu --------------------------------------------------------------

async function showQuickMenu(context) {
    const pick = await vscode.window.showQuickPick([
        { label: '$(play) Run Current File', description: 'gg run', action: 'run' },
        { label: '$(rocket) Run Current File (Release)', description: 'gg run --release (bounds checks stay on)', action: 'runRelease' },
        { label: '$(debug-alt) Debug Current File', description: 'gg build -g, then the native debugger', action: 'debug' },
        { label: '$(tools) Build Binary', description: 'gg build', action: 'build' },
        { label: '$(package) Build Binary (Release)', description: 'gg build --release', action: 'buildRelease' },
        { label: '$(search) Check Current File', description: 'gg check (diagnostics, no codegen)', action: 'check' },
        { label: '$(wrench) Apply Safe Fixes', description: 'gg fix', action: 'fix' },
        { label: '$(question) Explain Diagnostic', description: 'gg explain GGxxxx', action: 'explain' },
        { label: '$(paintcan) Format Current File', description: 'gg fmt (four spaces, else and elif level with if)', action: 'fmt' },
        { label: '$(beaker) Run Tests', description: 'gg test', action: 'test' },
        { label: '$(new-folder) Create New Project', description: 'gg new', action: 'newPackage' },
        { label: '$(plug) Generate C Bindings', description: 'gg bindgen', action: 'bindgen' },
        { label: '$(plug) Generate C++ Bindings', description: 'gg bindgen --cpp', action: 'bindgenCpp' },
        { label: '$(book) Generate Documentation', description: 'gg doc', action: 'doc' },
        { label: '$(lock) Write API Lock', description: 'gg api --lock', action: 'apiLock' },
        { label: '$(checklist) Check API Lock', description: 'gg api --check', action: 'apiCheck' },
        { label: '$(list-flat) List Targets', description: 'gg targets', action: 'targets' },
        { label: '$(circuit-board) Emit LLVM IR', description: 'gg emit-ll', action: 'emitLLVM' },
        { label: '$(file-binary) Emit LLVM Bitcode', description: 'gg emit-bc', action: 'emitBC' },
        { label: '$(symbol-structure) View AST', description: 'gg ast', action: 'showAst' },
        { label: '$(sync) Restart Language Server', description: 'gg lsp', action: 'restart' }
    ], { placeHolder: 'Greengold Development Actions' });

    if (!pick) return;
    switch (pick.action) {
        case 'run': executeTerminalCommand('run'); break;
        case 'runRelease': executeTerminalCommand('run', ['--release']); break;
        case 'debug': await debugCurrentFile(); break;
        case 'build': executeTerminalCommand('build'); break;
        case 'buildRelease': executeTerminalCommand('build', ['--release']); break;
        case 'check': executeTerminalCommand('check'); break;
        case 'fix': executeTerminalCommand('fix'); break;
        case 'explain': await vscode.commands.executeCommand('greengold.explain'); break;
        case 'fmt': executeTerminalCommand('fmt'); break;
        case 'test': executeTerminalCommand('test'); break;
        case 'newPackage': await createNewPackage(); break;
        case 'bindgen': await generateBindings(undefined, false); break;
        case 'bindgenCpp': await generateBindings(undefined, true); break;
        case 'doc': executeTerminalCommand('doc'); break;
        case 'apiLock': runInTerminal(['api', '--lock']); break;
        case 'apiCheck': runInTerminal(['api', '--check']); break;
        case 'targets': runInTerminal(['targets']); break;
        case 'emitLLVM': executeTerminalCommand('emit-ll'); break;
        case 'emitBC': executeTerminalCommand('emit-bc'); break;
        case 'showAst': executeTerminalCommand('ast'); break;
        case 'restart': await restartLanguageServer(context); break;
    }
}

// --- Debugger Support (Native LLVM / DAP) -----------------------------------

async function debugCurrentFile(targetUri) {
    let filePath;
    if (targetUri && targetUri.fsPath) {
        filePath = targetUri.fsPath;
    } else {
        const editor = vscode.window.activeTextEditor;
        if (!editor || !editor.document.fileName.endsWith('.gg')) {
            vscode.window.showWarningMessage('Please open a Greengold (.gg) file to debug.');
            return;
        }
        filePath = editor.document.fileName;
    }

    const gg = ggInvocation();
    const isWindows = process.platform === 'win32';
    const exeExt = isWindows ? '.exe' : '';
    const fileBase = path.basename(filePath, '.gg');
    const outExe = path.join(path.dirname(filePath), `${fileBase}${exeExt}`);

    // Build the binary first with debug info
    await vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: `Building ${fileBase} for debugging...`,
        cancellable: false
    }, async () => {
        return new Promise((resolve, reject) => {
            cp.execFile(gg.cmd, [...gg.pre, 'build', '-g', '--color', 'never', filePath, '-o', outExe], (err, stdout, stderr) => {
                if (err) {
                    vscode.window.showErrorMessage(`Greengold build failed:\n${stderr || stdout || err.message}`);
                    reject(err);
                } else {
                    resolve();
                }
            });
        });
    });

    if (!fs.existsSync(outExe)) {
        vscode.window.showErrorMessage(`Build succeeded but output binary was not found at: ${outExe}`);
        return;
    }

    // Determine debugger type
    const config = vscode.workspace.getConfiguration('greengold');
    let debuggerType = config.get('debug.debugger', 'auto');

    if (debuggerType === 'auto') {
        if (vscode.extensions.getExtension('vadimcn.vscode-lldb')) {
            debuggerType = 'lldb';
        } else if (isWindows && vscode.extensions.getExtension('ms-vscode.cpptools')) {
            debuggerType = 'cppvsdbg';
        } else if (vscode.extensions.getExtension('ms-vscode.cpptools')) {
            debuggerType = 'cppdbg';
        } else {
            debuggerType = 'lldb';
        }
    }

    const debugConfig = {
        name: `Debug: ${fileBase}`,
        type: debuggerType,
        request: 'launch',
        program: outExe,
        cwd: path.dirname(filePath),
        args: [],
        stopAtEntry: false
    };

    if (debuggerType === 'cppdbg') {
        debugConfig.MIMode = process.platform === 'darwin' ? 'lldb' : 'gdb';
    }

    const folder = vscode.workspace.getWorkspaceFolder(vscode.Uri.file(filePath));
    await vscode.debug.startDebugging(folder, debugConfig);
}

// --- Test Controller (VS Code Testing API) -----------------------------------

function registerTestController(context) {
    testController = vscode.tests.createTestController('greengoldTests', 'Greengold Tests');
    context.subscriptions.push(testController);

    // Run Profile
    testController.createRunProfile(
        'Run',
        vscode.TestRunProfileKind.Run,
        async (request, token) => {
            await runTestProfile(request, token);
        },
        true
    );

    // Scan initial documents and watch workspace files
    if (vscode.window.activeTextEditor) {
        updateTestsForDocument(vscode.window.activeTextEditor.document);
    }

    context.subscriptions.push(
        vscode.workspace.onDidOpenTextDocument(updateTestsForDocument),
        vscode.workspace.onDidChangeTextDocument((e) => updateTestsForDocument(e.document))
    );

    // Initial scan of workspace .gg files
    vscode.workspace.findFiles('**/*.gg', '**/node_modules/**').then((uris) => {
        for (const uri of uris) {
            vscode.workspace.openTextDocument(uri).then(updateTestsForDocument, () => {});
        }
    });
}

function findGreengoldTests(text) {
    const tests = [];
    const seen = new Map();
    const lines = text.split(/\r?\n/);
    let target = '';
    let implOwner = '';

    const push = (base, lineIndex, character) => {
        const n = (seen.get(base) || 0) + 1;
        seen.set(base, n);
        tests.push({
            name: n === 1 ? base : `${base}.${n}`,
            line: lineIndex,
            character: Math.max(character, 0),
        });
    };

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const code = line.replace(/\s+#.*$/, '');
        const top = !/^\s/.test(line);

        if (top) {
            const impl = /^impl\s+(?:[A-Za-z_][A-Za-z0-9_]*\.)?([A-Za-z_][A-Za-z0-9_]*)\b/.exec(code);
            if (impl) {
                implOwner = impl[1];
                continue;
            }
            const fn = /^(?:(?:hot|comptime)\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)\b/.exec(code);
            if (fn) {
                implOwner = '';
                target = fn[1];
                if (/^test_[A-Za-z0-9_]+$/.test(fn[1]) && /\(\s*\)\s*:/.test(code) && !/\)\s*->/.test(code)) {
                    push(fn[1], i, line.indexOf(fn[1]));
                }
                continue;
            }
            const block = /^test(?:\s+([A-Za-z_][A-Za-z0-9_]*))?\s*:/.exec(code);
            if (block) {
                const explicit = block[1] || '';
                const base = explicit
                    ? (target ? `${target}.${explicit}` : explicit)
                    : (target ? `${target}.test` : 'test');
                push(base, i, line.indexOf('test'));
                continue;
            }
            if (code.trim() && !code.startsWith('#')) {
                implOwner = '';
            }
            continue;
        }

        const method = /^\s+(?:hot\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)\b/.exec(code);
        if (method && implOwner) {
            target = `${implOwner}.${method[1]}`;
        }
    }
    return tests;
}

function updateTestsForDocument(document) {
    if (!testController || !document || document.languageId !== 'gg') {
        return;
    }

    const uri = document.uri;
    const fileId = uri.toString();
    const fileName = path.basename(document.fileName);

    const testNames = findGreengoldTests(document.getText());

    if (testNames.length === 0) {
        testController.items.delete(fileId);
        return;
    }

    let fileItem = testController.items.get(fileId);
    if (!fileItem) {
        fileItem = testController.createTestItem(fileId, fileName, uri);
        testController.items.add(fileItem);
    }

    // Keep active test items updated
    const currentTestIds = new Set();
    for (const t of testNames) {
        const testId = `${fileId}::${t.name}`;
        currentTestIds.add(testId);
        let testItem = fileItem.children.get(testId);
        if (!testItem) {
            testItem = testController.createTestItem(testId, t.name, uri);
            fileItem.children.add(testItem);
        }
        testItem.range = new vscode.Range(
            new vscode.Position(t.line, t.character),
            new vscode.Position(t.line, t.character + t.name.length + 3)
        );
    }

    // Remove obsolete test items
    fileItem.children.forEach((child) => {
        if (!currentTestIds.has(child.id)) {
            fileItem.children.delete(child.id);
        }
    });
}

async function runTestProfile(request, token) {
    if (!testController) return;
    const run = testController.createTestRun(request);
    const gg = ggInvocation();

    /** @type {vscode.TestItem[]} */
    const testsToRun = [];

    if (request.include) {
        for (const item of request.include) {
            if (item.children.size > 0) {
                item.children.forEach((child) => testsToRun.push(child));
            } else {
                testsToRun.push(item);
            }
        }
    } else {
        testController.items.forEach((fileItem) => {
            fileItem.children.forEach((child) => testsToRun.push(child));
        });
    }

    const byFile = new Map();
    for (const item of testsToRun) {
        const key = item.uri.fsPath;
        if (!byFile.has(key)) byFile.set(key, []);
        byFile.get(key).push(item);
    }

    for (const [fsPath, items] of byFile) {
        if (token.isCancellationRequested) break;
        for (const item of items) run.started(item);
        const startTime = Date.now();
        try {
            const result = await new Promise((resolve) => {
                cp.execFile(
                    gg.cmd,
                    [...gg.pre, 'test', '--json', '--color', 'never', fsPath],
                    { maxBuffer: 10 * 1024 * 1024 },
                    (err, stdout, stderr) => {
                        resolve({ err, stdout, stderr, duration: Date.now() - startTime });
                    }
                );
            });
            let doc = null;
            try {
                doc = JSON.parse(result.stdout);
            } catch (e) {
                doc = null;
            }
            const reports = doc && Array.isArray(doc.tests) ? doc.tests : null;
            if (!reports) {
                const message = new vscode.TestMessage((result.stderr || result.stdout || 'gg test failed').trim());
                for (const item of items) run.failed(item, message, result.duration);
                continue;
            }
            const buckets = new Map();
            for (const report of reports) {
                const list = buckets.get(report.name) || [];
                list.push(report);
                buckets.set(report.name, list);
            }
            for (const item of items) {
                const bucket = buckets.get(item.label);
                const report = bucket && bucket.shift();
                if (!report) {
                    run.failed(item, new vscode.TestMessage('gg test --json did not report this test'), result.duration);
                    continue;
                }
                if (report.status === 'passed') {
                    run.passed(item, result.duration);
                } else {
                    const message = new vscode.TestMessage(report.message || 'failed');
                    const line = Number(report.line);
                    if (line > 0) {
                        message.location = new vscode.Location(
                            item.uri,
                            new vscode.Range(line - 1, 0, line - 1, 0)
                        );
                    }
                    run.failed(item, message, result.duration);
                }
            }
        } catch (ex) {
            const message = new vscode.TestMessage(String(ex));
            for (const item of items) run.failed(item, message);
        }
    }

    run.end();
}

async function runSingleTestCommand(fileUri, testName) {
    const editor = vscode.window.activeTextEditor;
    const targetFile = fileUri ? fileUri.fsPath : (editor ? editor.document.fileName : null);

    if (!targetFile) {
        vscode.window.showWarningMessage('Please open a Greengold file first.');
        return;
    }

    const terminalName = 'Greengold Test';
    let terminal = vscode.window.terminals.find(t => t.name === terminalName);
    if (!terminal) {
        terminal = vscode.window.createTerminal(terminalName);
    }
    terminal.show();
    const gg = ggInvocation();
    terminal.sendText(`${ggShell(gg)} test "${targetFile}"`);
}

// --- CodeLens Provider -------------------------------------------------------

function registerCodeLens(context) {
    const codeLensProvider = {
        provideCodeLenses(document, token) {
            if (document.languageId !== 'gg') return [];
            const lenses = [];
            const text = document.getText();
            const lines = text.split(/\r?\n/);

            for (let i = 0; i < lines.length; i++) {
                const line = lines[i];

                // fn main():
                if (/^fn\s+main\(\)\s*:/.test(line)) {
                    const range = new vscode.Range(i, 0, i, line.length);
                    lenses.push(
                        new vscode.CodeLens(range, {
                            title: '▶ Run',
                            command: 'greengold.runFile'
                        }),
                        new vscode.CodeLens(range, {
                            title: '⚡ Release',
                            command: 'greengold.runRelease'
                        }),
                        new vscode.CodeLens(range, {
                            title: '🐞 Debug',
                            command: 'greengold.debugFile',
                            arguments: [document.uri]
                        })
                    );
                }

            }

            for (const t of findGreengoldTests(text)) {
                const range = new vscode.Range(t.line, t.character, t.line, t.character + t.name.length);
                lenses.push(
                    new vscode.CodeLens(range, {
                        title: '▶ Run Test',
                        command: 'greengold.runSingleTest',
                        arguments: [document.uri, t.name]
                    })
                );
            }

            return lenses;
        }
    };

    context.subscriptions.push(
        vscode.languages.registerCodeLensProvider({ language: 'gg', scheme: 'file' }, codeLensProvider)
    );
}

// --- Task Provider (Build Tasks) ---------------------------------------------

function registerTaskProvider(context) {
    const taskProvider = {
        provideTasks() {
            const gg = ggInvocation();
            const editor = vscode.window.activeTextEditor;
            const currentFile = editor && editor.document.fileName.endsWith('.gg')
                ? editor.document.fileName
                : '${file}';

            const tasks = [
                new vscode.Task(
                    { type: 'greengold', command: 'build' },
                    vscode.TaskScope.Workspace,
                    'gg build',
                    'greengold',
                    new vscode.ShellExecution(`${ggShell(gg)} build --color never "${currentFile}"`),
                    ['$greengold']
                ),
                new vscode.Task(
                    { type: 'greengold', command: 'build', release: true },
                    vscode.TaskScope.Workspace,
                    'gg build --release',
                    'greengold',
                    new vscode.ShellExecution(`${ggShell(gg)} build --release --color never "${currentFile}"`),
                    ['$greengold']
                ),
                new vscode.Task(
                    { type: 'greengold', command: 'check' },
                    vscode.TaskScope.Workspace,
                    'gg check',
                    'greengold',
                    new vscode.ShellExecution(`${ggShell(gg)} check --color never "${currentFile}"`),
                    ['$greengold']
                ),
                new vscode.Task(
                    { type: 'greengold', command: 'test' },
                    vscode.TaskScope.Workspace,
                    'gg test',
                    'greengold',
                    new vscode.ShellExecution(`${ggShell(gg)} test --color never`),
                    ['$greengold']
                ),
                new vscode.Task(
                    { type: 'greengold', command: 'fix' },
                    vscode.TaskScope.Workspace,
                    'gg fix',
                    'greengold',
                    new vscode.ShellExecution(`${ggShell(gg)} fix --color never "${currentFile}"`)
                ),
                new vscode.Task(
                    { type: 'greengold', command: 'fmt' },
                    vscode.TaskScope.Workspace,
                    'gg fmt',
                    'greengold',
                    new vscode.ShellExecution(`${ggShell(gg)} fmt`)
                )
            ];

            tasks[0].group = vscode.TaskGroup.Build;
            tasks[1].group = vscode.TaskGroup.Build;
            tasks[3].group = vscode.TaskGroup.Test;

            return tasks;
        },
        resolveTask(task) {
            return task;
        }
    };

    context.subscriptions.push(
        vscode.tasks.registerTaskProvider('greengold', taskProvider)
    );
}

// --- Project Wizard & C Bindings ---------------------------------------------

async function createNewPackage() {
    const name = await vscode.window.showInputBox({
        prompt: 'Enter the new Greengold package name',
        placeHolder: 'my_project'
    });
    if (!name) return;

    const folderUri = await vscode.window.showOpenDialog({
        canSelectFiles: false,
        canSelectFolders: true,
        canSelectMany: false,
        openLabel: 'Select Parent Directory'
    });
    const parentDir = folderUri && folderUri[0] ? folderUri[0].fsPath : null;

    const gg = ggInvocation();
    const args = [...gg.pre, 'new', name];
    if (parentDir) {
        args.push('--path', path.join(parentDir, name));
    }

    cp.execFile(gg.cmd, args, (err, stdout, stderr) => {
        if (err) {
            vscode.window.showErrorMessage(`Failed to create package: ${stderr || err.message}`);
        } else {
            const projectPath = parentDir ? path.join(parentDir, name) : path.join(process.cwd(), name);
            vscode.window.showInformationMessage(
                `Greengold package '${name}' created successfully!`,
                'Open Project'
            ).then((choice) => {
                if (choice === 'Open Project') {
                    vscode.commands.executeCommand('vscode.openFolder', vscode.Uri.file(projectPath));
                }
            });
        }
    });
}

async function generateBindings(headerUri, cpp) {
    let headerPath;
    if (headerUri && headerUri.fsPath) {
        headerPath = headerUri.fsPath;
    } else {
        const uris = await vscode.window.showOpenDialog({
            canSelectFiles: true,
            canSelectFolders: false,
            canSelectMany: false,
            filters: cpp
                ? { 'C++ Header Files': ['h', 'hpp', 'hh', 'hxx'] }
                : { 'C Header Files': ['h'] },
            openLabel: cpp ? 'Select C++ Header' : 'Select C Header'
        });
        if (!uris || !uris[0]) return;
        headerPath = uris[0].fsPath;
    }

    const outPath = headerPath.replace(/\.(hpp|hh|hxx|h)$/i, '.gg');
    const gg = ggInvocation();
    const args = [...gg.pre, 'bindgen'];
    if (cpp) args.push('--cpp');
    args.push(headerPath, '-o', outPath);

    cp.execFile(gg.cmd, args, (err, stdout, stderr) => {
        if (err) {
            vscode.window.showErrorMessage(`Failed to generate bindings: ${stderr || err.message}`);
        } else {
            vscode.window.showInformationMessage(`Greengold bindings generated at: ${path.basename(outPath)}`);
            vscode.workspace.openTextDocument(outPath).then((doc) => {
                vscode.window.showTextDocument(doc);
            });
        }
    });
}

// --- LSP Client Startup & Shutdown ------------------------------------------

async function startLanguageServer(context) {
    if (client) {
        return;
    }

    const config = vscode.workspace.getConfiguration('greengold');
    const gg = ggInvocation();
    const customCommand = config.get('languageServer.command', '');

    let serverOptions;
    if (customCommand) {
        const parts = customCommand.trim().split(/\s+/);
        serverOptions = {
            command: parts[0],
            args: parts.slice(1),
        };
    } else {
        serverOptions = {
            command: gg.cmd,
            args: [...gg.pre, 'lsp'],
            options: {
                env: {
                    ...process.env,
                    PYTHONUNBUFFERED: '1',
                    PYTHONIOENCODING: 'utf-8',
                }
            }
        };
    }

    const clientOptions = {
        documentSelector: [{ scheme: 'file', language: 'gg' }],
        synchronize: {
            fileEvents: vscode.workspace.createFileSystemWatcher('**/*.gg')
        }
    };

    client = new LanguageClient(
        'greengold-lsp',
        'Greengold Language Server',
        serverOptions,
        clientOptions
    );

    updateStatusBar('starting');

    try {
        await client.start();
        updateStatusBar('ready');
    } catch (err) {
        console.error('Failed to start Greengold Language Server:', err);
        updateStatusBar('error');
        notInstalledHint();
    }
}

async function stopLanguageServer() {
    if (!client) {
        return;
    }
    updateStatusBar('stopped');
    try {
        await client.stop();
    } catch (err) {
        console.error('Error stopping language client:', err);
    }
    client = null;
}

async function restartLanguageServer(context) {
    await stopLanguageServer();
    await startLanguageServer(context);
    vscode.window.showInformationMessage('Greengold Language Server successfully restarted.');
}

function updateStatusBar(status) {
    if (!statusBarItem) return;
    switch (status) {
        case 'starting':
            statusBarItem.text = '$(sync~spin) Greengold LSP';
            statusBarItem.tooltip = 'Starting Greengold Language Server...';
            statusBarItem.show();
            break;
        case 'ready':
            statusBarItem.text = '$(check) Greengold LSP';
            statusBarItem.tooltip = 'Greengold Language Server Active (Click: Menu)';
            statusBarItem.show();
            break;
        case 'error':
            statusBarItem.text = '$(error) Greengold LSP';
            statusBarItem.tooltip = 'Greengold Language Server Error (Click: Restart)';
            statusBarItem.show();
            break;
        case 'stopped':
            statusBarItem.hide();
            break;
    }
}

function runInTerminal(parts) {
    const terminalName = 'Greengold';
    let terminal = vscode.window.terminals.find(t => t.name === terminalName);
    if (!terminal) {
        terminal = vscode.window.createTerminal(terminalName);
    }
    terminal.show();
    const gg = ggInvocation();
    const quoted = parts.map((part) => /\s/.test(part) ? `"${part}"` : part);
    terminal.sendText(`${ggShell(gg)} ${quoted.join(' ')}`);
}

function executeTerminalCommand(cmd, extraArgs = []) {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showWarningMessage('Please open a Greengold (.gg) file first.');
        return;
    }
    const filePath = editor.document.uri.fsPath;
    if (!filePath.endsWith('.gg')) {
        vscode.window.showWarningMessage('Only .gg files can be run or built.');
        return;
    }
    runInTerminal([cmd, ...extraArgs, '--color', 'never', filePath]);
}

function deactivate() {
    return stopLanguageServer();
}

module.exports = {
    activate,
    deactivate
};
