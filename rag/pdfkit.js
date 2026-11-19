ObjC.import('PDFKit');

function run(argv) {
    const url = $.NSURL.fileURLWithPath(argv[0]);
    const document = $.PDFDocument.alloc.initWithURL(url);
    if (!document || !Number(document.pageCount)) throw new Error('Could not open PDF');
    const pages = [];
    for (let i = 0; i < Number(document.pageCount); i++) {
        const page = document.pageAtIndex(i);
        pages.push(ObjC.unwrap(page.string) || '');
    }
    return JSON.stringify(pages);
}
