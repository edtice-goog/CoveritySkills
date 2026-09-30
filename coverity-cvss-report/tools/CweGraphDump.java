/* Dump the CWE ancestor graph the CVSS Report Generator actually walks.
 *
 * The generator's findAncestors() follows `ChildOf` edges only, over the
 * graph CweDataProvider.getCwe2017() builds from the serialized 2017 CWE
 * data inside cov-reports.jar.  That graph is NOT the checker-to-CWE
 * taxonomy in issue-type-taxonomies-*.jar, and the difference matters:
 * the taxonomy's parent links include category membership, which
 * findAncestors does not traverse.
 *
 * Emits {"<cwe>": [<ChildOf parent ids>], ...} on stdout, so an audit can
 * reproduce the lookup exactly rather than approximate it.  A CWE with no
 * key here has no node in the graph at all -- no ancestors, therefore the
 * hardcoded zero vector, whatever the profile says.
 *
 * Compile and run against the installed generator's own lib directory:
 *
 *   javac -proc:none -cp "<reports>/lib/*" -d <tmp> CweGraphDump.java
 *   java -DOWASP=2017 -DSANS=2019 -cp "<tmp>;<reports>/lib/*" CweGraphDump
 *
 * cvss_profile_audit.py graph does both steps for you.
 */

import com.coverity.report.cwe.*;
import java.lang.reflect.*;
import java.util.*;

public class CweGraphDump {
    public static void main(String[] a) throws Exception {
        CweDataProvider p = new CweDataProvider();
        for (Field f : CweDataProvider.class.getDeclaredFields()) {
            if (f.getType().getSimpleName().equals("Deserialization")) {
                f.setAccessible(true);
                if (f.get(p) == null) {
                    Constructor<?> c = f.getType().getDeclaredConstructor();
                    c.setAccessible(true);
                    f.set(p, c.newInstance());
                }
            }
        }
        CweData d = p.getCwe2017();
        Map<CweNode, CweNode> all = d.allCweNodes;
        StringBuilder sb = new StringBuilder("{");
        boolean first = true;
        TreeMap<Integer, CweNode> byId = new TreeMap<>();
        for (CweNode n : all.keySet()) byId.put(n.id, n);
        for (Map.Entry<Integer, CweNode> e : byId.entrySet()) {
            Set<CweNode> parents =
                e.getValue().outEdge.getOrDefault("ChildOf", new HashSet<>());
            if (!first) sb.append(",");
            first = false;
            sb.append("\"").append(e.getKey()).append("\":[");
            TreeSet<Integer> pids = new TreeSet<>();
            for (CweNode q : parents) pids.add(q.id);
            boolean f2 = true;
            for (Integer i : pids) {
                if (!f2) sb.append(",");
                f2 = false;
                sb.append(i);
            }
            sb.append("]");
        }
        sb.append("}");
        System.out.println(sb);
        System.err.println("nodes=" + byId.size());
    }
}
