/* 项目维护的 pywebview API 工厂：在依赖初始化后、finish/createApi前安装。 */
(function () {
  const bridge = window.pywebview;
  if (!bridge) throw new Error('bridge-not-initialized');
  bridge._runBody = function (id, body) {
    let settled = false;
    const settle = result => {
      if (settled) return;
      const encoded = JSON.stringify(result);
      settled = true;
      bridge._asyncCallback(encoded, id);
    };
    return Promise.resolve().then(body).then(value => {
      try { settle({success:true,value:value === undefined ? null : value}); }
      catch (_) { settle({success:false,error:'javascript-result-serialization-failed'}); }
    }, () => settle({success:false,error:'javascript-execution-failed'}));
  };
  bridge._createApi = function (functions) {
    for (const entry of functions) {
      const names = entry.func.split('.');
      if (names.some(name => !/^[A-Za-z_$][\w$]*$/.test(name) || ['__proto__','prototype','constructor'].includes(name)))
        throw new Error('invalid-api-name');
      let owner = bridge.api;
      for (const name of names.slice(0,-1)) {
        if (!Object.hasOwn(owner,name)) owner[name] = Object.create(null);
        owner = owner[name];
      }
      bridge._returnValuesCallbacks[entry.func] = Object.create(null);
      owner[names.at(-1)] = function (...args) {
        const id = crypto.randomUUID();
        return new Promise((resolve,reject) => {
          bridge._checkValue(entry.func,resolve,reject,id);
          try { bridge._jsApiCallback(entry.func,args,id); }
          catch (error) { delete bridge._returnValuesCallbacks[entry.func][id]; reject(error); }
        });
      };
    }
  };
})();
