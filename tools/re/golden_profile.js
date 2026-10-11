// Run the official app's own offline-profile writer (GK6+ src/libs/profile.js) against a fake keyboard and
// record every packet it would send. Gives byte-exact reference output for our Python writer, no hardware needed.
//
//   node tools/re/golden_profile.js <asar dir> <profile.json> <out.json> [fixtures dir]
//
// The profile JSON is in the app's format (resources/device/<model>/data/profile_offline_*.json + edits). Effects
// and macros go into a temporary user-data dir, where the app looks for them: from [fixtures dir] (le/*.json and
// macro/*.cms as plain text, encoded here with the app's own CMF codec) or else the app's library
// (resources/res/data/{le,macro}). USB, Electron and the online-mode driver are stubbed out; nothing touches devices.
const fs = require('fs');
const os = require('os');
const path = require('path');
const Module = require('module');

const [asarArg, profileFile, outFile, fixtures] = process.argv.slice(2);
const asar = path.resolve(asarArg);
const modelId = '656802056';
const userdata = fs.mkdtempSync(path.join(os.tmpdir(), 'gk6x-golden-'));
process.env.APPDATA = userdata;   // app config.js: userdata_dir = $APPDATA/GK6XPlus-CMS
const appdata = path.join(userdata, 'GK6XPlus-CMS', 'Account', '0');
if (!fixtures) {
    for (const [src, dst] of [['le', 'LE'], ['macro', 'Macro']]) {
        fs.cpSync(path.join(asar, 'resources/res/data', src), path.join(appdata, dst), { recursive: true });
    }
}

const packets = [];
const fakeKeyboard = {
    probeInfo: { ModelID: Number(modelId), FWID: 0x84223311, FWVersion: 0x0576 },
    request(cmd) {
        const buf = cmd.req.toBuffer();
        packets.push(buf.toString('hex'));
        if (buf[0] === 0x01 && buf[1] === 0x09) return Promise.resolve({ key_col: 16, key_row: 8 });
        return Promise.resolve({ ack: 1, crc: 0 });
    },
};
const stubs = {
    [path.join(asar, 'src/libs/device.js')]: { listDevices: async () => [fakeKeyboard], getDevice: () => fakeKeyboard },
    [path.join(asar, 'src/libs/driver.js')]: class { static stopModelLE() {} static stopKeyMacro() {} },
};
const external = new Set(['node-hid', 'electron', 'usb-detection', 'uiohook-napi']);
const load = Module._load;
Module._load = function (request, parent, isMain) {
    if (external.has(request)) return {};
    const resolved = Module._resolveFilename(request, parent, isMain);
    return stubs[resolved] || load.apply(this, arguments);
};

const CMF = require(path.join(asar, 'src/libs/cmfcodec.js'));
const { applyConfig } = require(path.join(asar, 'src/libs/profile.js'));

(async () => {
    if (fixtures) {
        for (const [dir, ext, type, name] of [['le', '.le', CMF.Type.TYPE_LIGHT, 'light'],
                                             ['macro', '.cms', CMF.Type.TYPE_MACRO, 'MACRO']]) {
            for (const file of fs.readdirSync(path.join(fixtures, dir))) {
                const guid = path.parse(file).name;
                await CMF.encodeFile(path.join(appdata, dir === 'le' ? 'LE' : 'Macro', guid + ext), { type, name },
                    fs.readFileSync(path.join(fixtures, dir, file), 'utf8'));
            }
        }
    }
    const guid = 'OPENGK6X-GOLDEN';
    const profile = fs.readFileSync(profileFile, 'utf8').replace(/^﻿/, '');
    await CMF.encodeFile(path.join(appdata, 'Devices', modelId, `${guid}.cmf`),
        { type: CMF.Type.TYPE_PROFILE, name: 'profile' }, profile);
    await applyConfig(0, modelId, guid);
    fs.writeFileSync(outFile, JSON.stringify(packets, null, 0));
    fs.rmSync(userdata, { recursive: true, force: true });
    process.stderr.write(`${packets.length} packets -> ${outFile}\n`);
})();
