const assert=require('assert');
const {merge,splitBlocks,looseKey}=require('../frontend/block-merge.js');
// looseKey ignores markup, entities and punctuation but keeps words
assert.strictEqual(looseKey('Para with <kbd>Ctrl</kbd> and &amp; entity &copy;'),looseKey('Para with Ctrl and & entity ©'));
assert.strictEqual(looseKey('***'),'HR'); assert.strictEqual(looseKey('---'),'HR');
assert.strictEqual(looseKey('<!-- note -->'),'');
// blocks: fences keep blank lines, lists and quotes stay whole, definitions split per line
assert.strictEqual(splitBlocks('a\n\nb').length,2);
assert.strictEqual(splitBlocks('```\nx\n\ny\n```\n\nz').length,2);
assert.strictEqual(splitBlocks('- a\n\n  more\n\n- b').length,1);
assert.strictEqual(splitBlocks('> a\n>\n> b\n\nc').length,2);
assert.strictEqual(splitBlocks('[1]: http://a\n[2]: http://b').length,2);
// nothing edited: the original comes back byte for byte
const original='Title\n=====\n\nSee [r][1].\n\n<!-- keep -->\n\n***\n\nEnd\n\n[1]: http://x "X"\n';
const base='# Title\n\nSee [r](http://x "X").\n\n---\n\nEnd';
assert.strictEqual(merge(original,base,base),original);
// one paragraph edited: only it changes
assert.strictEqual(merge(original,base,base.replace('End','End!')),original.replace('End','End!'));
// block deleted
assert.strictEqual(merge(original,base,base.replace('\n\nEnd','')),original.replace('End\n\n',''));
// block added
const added=merge(original,base,base.replace('---\n\nEnd','---\n\nNew\n\nEnd'));
assert.ok(added.includes('Title\n=====')&&added.includes('<!-- keep -->')&&added.includes('New\n\nEnd')&&added.includes('[1]: http://x "X"'));
// moved block (footnote definition ends up last in base): stays where it was, no duplicate
const o2='A[^1]\n\n[^1]: Note\n\nB\n';const b2='A[^1]\n\nB\n\n[^1]: Note';
assert.strictEqual(merge(o2,b2,b2),o2);
assert.strictEqual(merge(o2,b2,b2.replace('B','B2')),o2.replace('B','B2'));
// very large inputs fall back to the plain conversion instead of hanging
const big=Array.from({length:3000},(_,i)=>'p'+i).join('\n\n');
assert.strictEqual(typeof merge(big,big,big+'\n\nx'),'string');
// a paragraph added after the very last original paragraph is separated by a blank line
assert.strictEqual(merge('A\n\nB','A\n\nB','A\n\nB\n\nC'),'A\n\nB\n\nC');
console.log('block-merge: all assertions passed');
