package com.eddygamedev.mgs3recomp

import android.app.Activity
import android.app.NativeActivity
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.net.Uri
import android.os.Bundle
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.zip.Inflater

/**
 * Launcher for the MGS3 static recompilation port.
 *
 * No game data ships with the app or the repository. The user picks their own
 * disc image (SAF), which is copied into the app's private storage. The
 * launcher then:
 *
 *  1. parses the ISO9660 file system and extracts the packed boot executable
 *     (SYSTEM.CNF -> BOOT2, e.g. SLES_820.42;1),
 *  2. inflates the zlib stream embedded at offset 0x1004 of that executable —
 *     this yields the real EE payload (1,084,340 bytes),
 *  3. wraps the payload in a minimal ELF32 image (single RWX PT_LOAD at
 *     0x100000, entry 0x100024) that the recompiled runtime can boot directly,
 *     bypassing the packed loader stub entirely,
 *  4. starts the NativeActivity, which runs the recompiled game.
 *
 * The disc image is also used in place by the runtime for real-LBN sector
 * reads (sceCdRead), so nothing is extracted wholesale.
 */
class LauncherActivity : Activity() {

    private companion object {
        const val PICK_ISO_REQUEST = 1001

        // Packed loader layout (SLES_820.42;1).
        const val ZLIB_OFFSET = 0x1004
        const val PAYLOAD_BYTES = 0x108BB4 // 1,084,340
        const val PAYLOAD_VADDR = 0x100000
        const val ENTRY_POINT = 0x100024

        const val SECTOR = 2048
    }

    private lateinit var statusText: TextView
    private lateinit var playButton: Button
    private lateinit var selectButton: Button

    private val gameDir: File by lazy {
        File(getExternalFilesDir(null), "game").apply { mkdirs() }
    }
    private val workDir: File by lazy {
        File(filesDir, "game").apply { mkdirs() }
    }

    private val discFile: File get() = File(gameDir, "disc.iso")
    private val bootFile: File get() = File(workDir, "boot.elf")
    private val analysisFile: File get() = File(gameDir, "MGS3_analysis.elf")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        buildUi()
        refreshReadyState("Import your own copy of the game disc (ISO) to begin.")
    }

    // ------------------------------------------------------------------ UI

    private fun buildUi() {
        val pad = (resources.displayMetrics.density * 16).toInt()

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.parseColor("#101018"))
            setPadding(pad * 2, pad * 2, pad * 2, pad * 2)
        }

        val title = TextView(this).apply {
            text = "Metal Gear Solid 3 — Native Android Port"
            textSize = 20f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
        }

        statusText = TextView(this).apply {
            setTextColor(Color.parseColor("#9fd0ff"))
            textSize = 14f
            setPadding(0, pad, 0, pad)
        }

        selectButton = Button(this).apply {
            text = "1. Select game disc image (.iso)"
            setOnClickListener { pickIso() }
        }

        playButton = Button(this).apply {
            text = "2. Play"
            isEnabled = false
            setOnClickListener { startGame() }
        }

        val note = TextView(this).apply {
            text = ("Your disc image is copied into this app's private storage and used " +
                    "in place for streaming. Nothing is uploaded and no game data is included " +
                    "with this app. A legally obtained dump of your own disc is required.")
            textSize = 12f
            setTextColor(Color.GRAY)
            setPadding(0, pad, 0, 0)
        }

        root.addView(title)
        root.addView(statusText)
        root.addView(selectButton)
        root.addView(playButton)
        root.addView(note)
        setContentView(root)
    }

    private fun setStatus(text: String) {
        statusText.text = text
    }

    private fun refreshReadyState(message: String) {
        selectButton.isEnabled = true
        val ready = analysisFile.exists() && discFile.exists()
        playButton.isEnabled = ready
        statusText.text = if (ready) "$message\nReady: ${analysisFile.absolutePath}" else message
    }

    // -------------------------------------------------------------- import

    private fun pickIso() {
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "*/*"
        }
        startActivityForResult(intent, PICK_ISO_REQUEST)
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != PICK_ISO_REQUEST || resultCode != RESULT_OK || data?.data == null) return
        importDisc(data.data!!)
    }

    private fun importDisc(uri: Uri) {
        selectButton.isEnabled = false
        playButton.isEnabled = false
        setStatus("Copying disc image…")
        Thread {
            try {
                copyUriToFile(uri, discFile) { copied, total ->
                    runOnUiThread {
                        setStatus("Copying disc image… %.2f / %.2f GB".format(copied / 1e9, total / 1e9))
                    }
                }
                runOnUiThread { setStatus("Extracting boot executable from ISO…") }
                val boot = extractBootElf(discFile, workDir)
                runOnUiThread { setStatus("Inflating payload and building boot ELF…") }
                buildAnalysisElf(boot, analysisFile)
                runOnUiThread {
                    refreshReadyState("Done — disc imported and boot ELF built.")
                    Toast.makeText(this, "Ready to play", Toast.LENGTH_SHORT).show()
                }
            } catch (t: Throwable) {
                runOnUiThread {
                    refreshReadyState("Failed: ${t.message}")
                    Toast.makeText(this, "Import failed: ${t.message}", Toast.LENGTH_LONG).show()
                }
            }
        }.start()
    }

    private fun startGame() {
        if (!analysisFile.exists() || !discFile.exists()) {
            Toast.makeText(this, "Import a disc image first", Toast.LENGTH_SHORT).show()
            return
        }
        startActivity(Intent(this, NativeActivity::class.java))
    }

    private fun copyUriToFile(uri: Uri, target: File, onProgress: (Long, Long) -> Unit) {
        val sizeHint = contentResolver.openAssetFileDescriptor(uri, "r")?.use { it.length } ?: -1L
        contentResolver.openInputStream(uri)?.use { input ->
            FileOutputStream(target).use { output ->
                val buf = ByteArray(1 shl 20)
                var copied = 0L
                var lastReport = 0L
                while (true) {
                    val n = input.read(buf)
                    if (n < 0) break
                    output.write(buf, 0, n)
                    copied += n
                    if (sizeHint > 0 && copied - lastReport > (64L shl 20)) {
                        lastReport = copied
                        onProgress(copied, sizeHint)
                    }
                }
            }
        } ?: error("Cannot open the selected file")
    }

    // ------------------------------------------------------------- ISO9660

    private class DirEntry(val extent: Int, val size: Int, val isDir: Boolean, val name: String)

    private fun readSector(raf: RandomAccessFile, sector: Int): ByteArray {
        raf.seek(sector.toLong() * SECTOR)
        val buf = ByteArray(SECTOR)
        raf.readFully(buf)
        return buf
    }

    private fun le32(b: ByteArray, off: Int): Int =
        (b[off].toInt() and 0xFF) or
            ((b[off + 1].toInt() and 0xFF) shl 8) or
            ((b[off + 2].toInt() and 0xFF) shl 16) or
            ((b[off + 3].toInt() and 0xFF) shl 24)

    private fun parseDirRecord(data: ByteArray, offset: Int): DirEntry? {
        val len = data[offset].toInt() and 0xFF
        if (len == 0) return null
        val extent = le32(data, offset + 2)
        val size = le32(data, offset + 10)
        val flags = data[offset + 25].toInt()
        val nameLen = data[offset + 32].toInt() and 0xFF
        val name = String(data, offset + 33, nameLen, Charsets.US_ASCII)
        return DirEntry(extent, size, (flags and 2) != 0, name)
    }

    private fun readDir(raf: RandomAccessFile, extent: Int, size: Int): List<DirEntry> {
        raf.seek(extent.toLong() * SECTOR)
        val data = ByteArray(size)
        raf.readFully(data)
        val out = ArrayList<DirEntry>()
        var pos = 0
        while (pos < data.size) {
            val recLen = data[pos].toInt() and 0xFF
            if (recLen == 0) {
                pos = ((pos / SECTOR) + 1) * SECTOR
                continue
            }
            parseDirRecord(data, pos)?.let { out.add(it) }
            pos += recLen
        }
        return out
    }

    private fun lookup(raf: RandomAccessFile, root: DirEntry, path: String): DirEntry? {
        var node = root
        val parts = path.replace("\\", "/").split("/").filter { it.isNotEmpty() }
        for (rawPart in parts) {
            val part = rawPart.uppercase()
            var found: DirEntry? = null
            for (entry in readDir(raf, node.extent, node.size)) {
                val n = entry.name.uppercase()
                if (n == part || n.startsWith("$part;")) {
                    found = entry
                    break
                }
            }
            node = found ?: return null
        }
        return node
    }

    private fun parseBoot2(cnf: String): String? {
        for (line in cnf.lines()) {
            val t = line.trim()
            if (t.startsWith("BOOT2")) {
                val value = t.substringAfter('=').trim().trimEnd(';').trim()
                return value
                    .removePrefix("cdrom0:\\")
                    .removePrefix("cdrom0:/")
                    .replace("\\", "/")
            }
        }
        return null
    }

    private fun readRange(raf: RandomAccessFile, extent: Int, size: Int): ByteArray {
        raf.seek(extent.toLong() * SECTOR)
        val data = ByteArray(size)
        raf.readFully(data)
        return data
    }

    private fun copyRange(raf: RandomAccessFile, extent: Int, size: Int, out: File) {
        raf.seek(extent.toLong() * SECTOR)
        FileOutputStream(out).use { fos ->
            val buf = ByteArray(1 shl 20)
            var remaining = size
            while (remaining > 0) {
                val chunk = minOf(buf.size, remaining)
                raf.readFully(buf, 0, chunk)
                fos.write(buf, 0, chunk)
                remaining -= chunk
            }
        }
    }

    /** Extracts SYSTEM.CNF -> BOOT2 (e.g. SLES_820.42;1) from the ISO. */
    private fun extractBootElf(iso: File, outDir: File): File {
        outDir.mkdirs()
        RandomAccessFile(iso, "r").use { raf ->
            val pvd = readSector(raf, 16)
            val id = String(pvd, 1, 5, Charsets.US_ASCII)
            require(id == "CD001") { "Not a valid ISO9660 image" }
            val root = parseDirRecord(pvd, 156) ?: error("ISO root directory missing")

            val cnf = lookup(raf, root, "SYSTEM.CNF")
                ?: error("SYSTEM.CNF not found — is this a PS2 disc?")
            val cnfText = String(readRange(raf, cnf.extent, cnf.size), Charsets.US_ASCII)
            val bootPath = parseBoot2(cnfText) ?: error("BOOT2 line missing in SYSTEM.CNF")

            val boot = lookup(raf, root, bootPath)
                ?: error("Boot file '$bootPath' not found on disc")
            val out = File(outDir, "boot.elf")
            copyRange(raf, boot.extent, boot.size, out)
            return out
        }
    }

    // --------------------------------------------- payload + analysis ELF

    /**
     * Inflates the zlib stream embedded in the packed boot executable and
     * wraps the resulting EE payload in a minimal ELF32 image the runtime
     * boots directly (entry 0x100024, load address 0x100000).
     */
    private fun buildAnalysisElf(boot: File, out: File) {
        val bootBytes = boot.readBytes()
        require(bootBytes.size > ZLIB_OFFSET + 16) { "Boot ELF too small" }
        require(
            bootBytes[0] == 0x7F.toByte() && bootBytes[1] == 'E'.code.toByte() &&
                bootBytes[2] == 'L'.code.toByte() && bootBytes[3] == 'F'.code.toByte()
        ) { "Boot file is not an ELF" }

        val inflater = Inflater()
        inflater.setInput(bootBytes, ZLIB_OFFSET, bootBytes.size - ZLIB_OFFSET)
        val payload = ByteArrayOutputStream(PAYLOAD_BYTES)
        val buf = ByteArray(1 shl 16)
        try {
            while (!inflater.finished()) {
                val n = inflater.inflate(buf)
                if (n > 0) {
                    payload.write(buf, 0, n)
                } else if (inflater.needsInput()) {
                    error("Truncated zlib stream in boot executable")
                }
            }
        } finally {
            inflater.end()
        }
        val image = payload.toByteArray()
        require(image.size == PAYLOAD_BYTES) {
            "Unexpected payload size ${image.size} (expected $PAYLOAD_BYTES) — wrong disc?"
        }

        // e_flags from the boot ELF header (offset 36), mirrored for
        // authenticity (ABI flags: mips32r2 + FPU bits).
        val eFlags = le32(bootBytes, 36)

        out.parentFile?.mkdirs()
        FileOutputStream(out).use { it.write(makeAnalysisElfBytes(image, eFlags)) }
    }

    /** Byte-exact port of scripts/make_analysis_elf.py. */
    private fun makeAnalysisElfBytes(image: ByteArray, eFlags: Int): ByteArray {
        val ehSize = 52
        val phEntSize = 32
        val phNum = 1
        val shEntSize = 40
        val shNum = 3
        val phOff = ehSize
        val dataOff = phOff + phNum * phEntSize
        val shstrtab = byteArrayOf(
            0, '.'.code.toByte(), 't'.code.toByte(), 'e'.code.toByte(), 'x'.code.toByte(), 't'.code.toByte(), 0,
            '.'.code.toByte(), 's'.code.toByte(), 'h'.code.toByte(), 's'.code.toByte(), 't'.code.toByte(),
            'r'.code.toByte(), 't'.code.toByte(), 'a'.code.toByte(), 'b'.code.toByte(), 0
        )
        var shOff = dataOff + image.size + shstrtab.size
        val pad = (4 - (shOff % 4)) % 4
        shOff += pad

        val b = ByteBuffer.allocate(shOff + shNum * shEntSize).order(ByteOrder.LITTLE_ENDIAN)

        // ---- ELF header -------------------------------------------------
        b.put(0x7F.toByte())
        b.put('E'.code.toByte())
        b.put('L'.code.toByte())
        b.put('F'.code.toByte())
        b.put(1) // ELFCLASS32
        b.put(1) // ELFDATA2LSB
        b.put(1) // EV_CURRENT
        b.put(0) // ELFOSABI_NONE
        b.put(0) // ABI version
        repeat(7) { b.put(0) } // padding
        b.putShort(2) // e_type = ET_EXEC
        b.putShort(8) // e_machine = EM_MIPS
        b.putInt(1) // e_version
        b.putInt(ENTRY_POINT)
        b.putInt(phOff)
        b.putInt(shOff)
        b.putInt(eFlags)
        b.putShort(ehSize.toShort())
        b.putShort(phEntSize.toShort())
        b.putShort(phNum.toShort())
        b.putShort(shEntSize.toShort())
        b.putShort(shNum.toShort())
        b.putShort(2) // e_shstrndx

        // ---- Program header: single RWX PT_LOAD -------------------------
        b.putInt(1) // PT_LOAD
        b.putInt(0) // p_offset
        b.putInt(PAYLOAD_VADDR)
        b.putInt(PAYLOAD_VADDR)
        b.putInt(image.size)
        b.putInt(image.size)
        b.putInt(7) // PF_R | PF_W | PF_X
        b.putInt(0x1000)

        // ---- payload + section name table -------------------------------
        b.put(image)
        b.put(shstrtab)
        repeat(pad) { b.put(0) }

        // NULL section
        repeat(shEntSize) { b.put(0) }

        // .text: name=1, type=PROGBITS, flags=ALLOC|EXECINSTR
        b.putInt(1)
        b.putInt(1)
        b.putInt(6)
        b.putInt(PAYLOAD_VADDR)
        b.putInt(dataOff)
        b.putInt(image.size)
        b.putInt(0)
        b.putInt(4)
        b.putInt(0)
        b.putInt(0)

        // .shstrtab: name=7, type=STRTAB
        b.putInt(7)
        b.putInt(3)
        b.putInt(0)
        b.putInt(0)
        b.putInt(dataOff + image.size)
        b.putInt(shstrtab.size)
        b.putInt(0)
        b.putInt(1)
        b.putInt(0)
        b.putInt(0)

        check(b.remaining() == 0) { "ELF builder size mismatch" }
        return b.array()
    }
}
