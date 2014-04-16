mv pautomount.py /usr/bin/pautomount
chmod +x /usr/bin/pautomount
mv pautomount.init /etc/init.d/pautomount
chmod +x /etc/init.d/pautomount
mv pautomount.conf /etc/pautomount.conf
update-rc.d pautomount defaults
